use crate::network::{StorageBehaviour, DirectRequest, DirectResponse, Manifest, encode_data, decode_data, DATA_SHARDS, PARITY_SHARDS, TOTAL_SHARDS};
use libp2p::swarm::SwarmEvent;
use libp2p::Swarm;
use tokio::sync::{mpsc, oneshot};
use futures::StreamExt;
use std::collections::HashMap;
use std::str::FromStr;
use sha2::{Sha256, Digest};
use libp2p::kad::{Record, RecordKey, Quorum, store::RecordStore};
use libp2p::request_response;
use libp2p::PeerId;
use std::sync::Arc;
use crate::peer_cache::PeerCache;
use crate::quota::{StorageClass, StorageQuotaManager};

pub struct FetchState {
    pub sender: Option<oneshot::Sender<Option<Vec<u8>>>>,
    pub shards: Vec<Option<Vec<u8>>>,
    pub received: usize,
    pub failed: usize,
    pub original_size: usize,
    pub manifest: Option<Manifest>,
}

pub fn do_self_healing(
    hash: &str,
    state: &mut FetchState,
    swarm: &mut Swarm<StorageBehaviour>,
    peer_cache: &PeerCache,
    local_peer_id: PeerId,
) {
    println!("Self-Healing: file {} has {} failed shards. Rebuilding...", hash, state.failed);
    if let Ok(decoded) = decode_data(state.shards.clone(), state.original_size) {
        if let Ok(new_shards) = encode_data(&decoded) {
            let mut new_manifest = state.manifest.clone().unwrap_or(Manifest {
                file_hash: hash.to_string(),
                size: state.original_size,
                storage_class: None,
                shards: HashMap::new(),
            });
            
            let top_peers = peer_cache.top_n_addrs(45);
            let mut target_peers = Vec::new();
            for addr_str in top_peers {
                if let Ok(ma) = libp2p::Multiaddr::from_str(&addr_str) {
                    for p in ma.iter() {
                        if let libp2p::multiaddr::Protocol::P2p(mh) = p {
                            if let Ok(pid) = PeerId::from_multihash(mh.into()) {
                                target_peers.push(pid);
                                break;
                            }
                        }
                    }
                }
            }
            if target_peers.is_empty() {
                target_peers.push(local_peer_id);
            }

            for (i, maybe_shard) in state.shards.iter().enumerate() {
                if maybe_shard.is_none() {
                    let repaired_shard = new_shards[i].clone();
                    let target_peer = target_peers[i % target_peers.len()];
                    new_manifest.shards.insert(i, target_peer.to_string());
                    let chunk_key = format!("{}_chunk_{}", hash, i);
                    
                    if target_peer != local_peer_id {
                        let _ = swarm.behaviour_mut().req_resp.send_request(
                            &target_peer,
                            DirectRequest::StoreShard { chunk_key: chunk_key.clone(), data: repaired_shard }
                        );
                    } else {
                        let record = Record {
                            key: RecordKey::new(&chunk_key),
                            value: repaired_shard,
                            publisher: None,
                            expires: None,
                        };
                        let _ = swarm.behaviour_mut().kademlia.store_mut().put(record);
                    }
                }
            }
            
            if let Ok(manifest_bytes) = serde_json::to_vec(&new_manifest) {
                let manifest_record = Record {
                    key: RecordKey::new(&format!("{}_manifest", hash)),
                    value: manifest_bytes,
                    publisher: None,
                    expires: None,
                };
                let _ = swarm.behaviour_mut().kademlia.store_mut().put(manifest_record);
                let _ = swarm.behaviour_mut().kademlia.start_providing(RecordKey::new(&hash));
                println!("Self-Healing completed for {}", hash);
            }
        }
    }
}

use serde::{Serialize, Deserialize};

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct PeerAnnounce {
    pub peer_id: String,
    pub listen_addrs: Vec<String>,
    pub timestamp: u64,
    pub nonce: Option<String>,
    pub signature: Option<String>,
    pub public_key: Option<String>,
    pub storage_status: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub quota_status: Option<serde_json::Value>,
    pub is_supernode: Option<bool>,
    pub api_url: Option<String>,
}

pub enum SwarmCommand {
    DhtUpload(Vec<u8>, StorageClass, String, oneshot::Sender<String>),
    DhtDownload(String, oneshot::Sender<Option<Vec<u8>>>),
    DhtDelete(String, oneshot::Sender<Option<u64>>),
    SavePeerCache,
    GcPeerCache(u64), // days
    AnnouncePeer,
    Publish(String, Vec<u8>),
    SubscribeTopic(String),
}

pub async fn run_swarm(
    mut swarm: Swarm<StorageBehaviour>,
    mut command_rx: mpsc::UnboundedReceiver<SwarmCommand>,
    local_key: libp2p::identity::Keypair,
    storage_full: std::sync::Arc<std::sync::atomic::AtomicBool>,
    event_tx: tokio::sync::broadcast::Sender<(String, Vec<u8>)>,
    quota_manager: Arc<StorageQuotaManager>,
) {
    let mut peer_cache = PeerCache::default();
    let peer_cache_path = "peer_cache.json";
    peer_cache = PeerCache::load(peer_cache_path);

    let mut active_fetches: HashMap<String, FetchState> = HashMap::new();
    let mut manifest_queries: HashMap<libp2p::kad::QueryId, String> = HashMap::new();
    let mut query_to_fetch: HashMap<libp2p::kad::QueryId, (String, usize)> = HashMap::new();
    let mut req_resp_to_fetch: HashMap<request_response::OutboundRequestId, (String, usize)> = HashMap::new();

    let mut bootstrap_interval = tokio::time::interval(std::time::Duration::from_secs(300));
    let mut telemetry_tick = tokio::time::interval(std::time::Duration::from_secs(300));
    // Initial bootstrap is good to have shortly after startup
    let mut initial_bootstrap = true;

    // Publish our HTTP URL to Kademlia
    let http_port: u16 = std::env::var("HTTP_PORT").unwrap_or_else(|_| "3001".to_string()).parse().unwrap_or(3001);
    let public_ip = match std::env::var("PUBLIC_IP") {
        Ok(ip) => ip,
        Err(_) => {
            match reqwest::get("https://api.ipify.org").await {
                Ok(resp) => resp.text().await.unwrap_or_else(|_| "127.0.0.1".to_string()),
                Err(_) => "127.0.0.1".to_string(),
            }
        }
    };
    let http_url = format!("http://{}:{}", public_ip, http_port);
    let key = libp2p::kad::RecordKey::new(&format!("/feedo/storage/http/{}", swarm.local_peer_id()));
    let record = libp2p::kad::Record {
        key,
        value: http_url.clone().into_bytes(),
        publisher: None,
        expires: None,
    };
    if let Err(e) = swarm.behaviour_mut().kademlia.put_record(record, libp2p::kad::Quorum::One) {
        println!("Failed to publish HTTP URL to Kademlia: {:?}", e);
    } else {
        println!("Published HTTP URL to Kademlia: {}", http_url);
    }

    loop {
        tokio::select! {
            _ = bootstrap_interval.tick() => {
                if initial_bootstrap {
                    initial_bootstrap = false;
                } else {
                    println!("Triggering periodic Kademlia bootstrap...");
                    let _ = swarm.behaviour_mut().kademlia.bootstrap();
                }
            }
            _ = telemetry_tick.tick() => {
                let node_id = swarm.local_peer_id().to_string();
                let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
                let (used_bytes, _) = quota_manager.usage();
                let stats = crate::telemetry::TelemetryStats {
                    storage_used_bytes: used_bytes,
                    total_requests: 0, // Implement later if needed
                    vectors_processed: 0,
                    pbft_votes_processed: 0,
                    blocks_finalized: 0,
                };
                let report = crate::telemetry::TelemetryReport {
                    node_id,
                    node_type: "storage".to_string(),
                    timestamp: now,
                    stats,
                };
                if let Ok(data) = serde_json::to_vec(&report) {
                    let topic = libp2p::gossipsub::IdentTopic::new("feedo_telemetry");
                    let _ = swarm.behaviour_mut().gossipsub.publish(topic, data);
                }
            }
            event = swarm.select_next_some() => {
                match event {
                    SwarmEvent::NewListenAddr { address, .. } => {
                        println!("Listening on P2P address: {}", address);
                    }
                    SwarmEvent::ConnectionEstablished { peer_id, .. } => {
                        println!("Connection established with {}", peer_id);
                        peer_cache.add_or_update(&peer_id.to_string(), vec![], true);
                    }
                    SwarmEvent::Behaviour(crate::network::StorageBehaviourEvent::Kademlia(libp2p::kad::Event::OutboundQueryProgressed { id, result, .. })) => {
                        match result {
                            libp2p::kad::QueryResult::GetRecord(Ok(libp2p::kad::GetRecordOk::FoundRecord(record))) => {
                                if let Some(hash) = manifest_queries.remove(&id) {
                                    if let Ok(manifest) = serde_json::from_slice::<Manifest>(&record.record.value) {
                                        println!("Manifest received from DHT for {}. Starting parallel shard download...", hash);
                                        if let Some(state) = active_fetches.get_mut(&hash) {
                                            state.manifest = Some(manifest.clone());
                                            state.original_size = manifest.size;
                                        }
                                        for (index, peer_id_str) in manifest.shards {
                                            if let Ok(peer_id) = PeerId::from_str(&peer_id_str) {
                                                let chunk_key = format!("{}_chunk_{}", hash, index);
                                                let req_id = swarm.behaviour_mut().req_resp.send_request(
                                                    &peer_id,
                                                    DirectRequest::FetchShard { chunk_key }
                                                );
                                                req_resp_to_fetch.insert(req_id, (hash.clone(), index));
                                            }
                                        }
                                    }
                                } else if let Some((hash, index)) = query_to_fetch.remove(&id) {
                                    if let Some(state) = active_fetches.get_mut(&hash) {
                                        if state.shards[index].is_none() {
                                            state.shards[index] = Some(record.record.value);
                                            state.received += 1;
                                            if state.received >= DATA_SHARDS {
                                                println!("Collected {}/{} shards for {} via DHT. Restoring...", DATA_SHARDS, TOTAL_SHARDS, hash);
                                                if let Ok(decoded) = decode_data(state.shards.clone(), state.original_size) {
                                                    if let Some(sender) = state.sender.take() {
                                                        let _ = sender.send(Some(decoded));
                                                    }
                                                }
                                                active_fetches.remove(&hash);
                                            }
                                        }
                                    }
                                }
                            }
                            libp2p::kad::QueryResult::GetRecord(Ok(libp2p::kad::GetRecordOk::FinishedWithNoAdditionalRecord { .. })) |
                            libp2p::kad::QueryResult::GetRecord(Err(_)) => {
                                if let Some(hash) = manifest_queries.remove(&id) {
                                    println!("DHT search failed or finished without finding manifest for {}", hash);
                                    if let Some(mut state) = active_fetches.remove(&hash) {
                                        if let Some(sender) = state.sender.take() {
                                            let _ = sender.send(None);
                                        }
                                    }
                                }
                            }
                            _ => {}
                        }
                    }
                    SwarmEvent::Behaviour(crate::network::StorageBehaviourEvent::Kademlia(libp2p::kad::Event::RoutingUpdated { peer, is_new_peer, addresses, .. })) => {
                        if is_new_peer {
                            println!("Kademlia DHT discovered a new node: {}", peer);
                        }
                        let addrs: Vec<String> = addresses.iter().map(|a| a.to_string()).collect();
                        peer_cache.add_or_update(&peer.to_string(), addrs, true);
                    }
                    SwarmEvent::Behaviour(crate::network::StorageBehaviourEvent::Gossipsub(libp2p::gossipsub::Event::Message { message, .. })) => {
                        let topic_str = message.topic.as_str().to_string();
                        let _ = event_tx.send((topic_str.clone(), message.data.clone()));
                        
                        if topic_str == "storage_announcements" {
                            if let Ok(announce) = serde_json::from_slice::<PeerAnnounce>(&message.data) {
                                let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
                                if announce.timestamp > now + 60 || now.saturating_sub(announce.timestamp) > 60 * 60 {
                                    println!("Ignoring stale/future announce from {}", announce.peer_id);
                                } else {
                                    peer_cache.add_or_update(&announce.peer_id, announce.listen_addrs.clone(), true);
                                    if let Some(url) = announce.api_url {
                                        peer_cache.update_api_url(&announce.peer_id, url);
                                    }
                                    if let Some(src) = message.source {
                                        if src.to_string() != announce.peer_id {
                                            println!("Announce peer_id {} does not match message source {}. Ignored.", announce.peer_id, src);
                                        } else {
                                            println!("Received peer announce from {} (addrs: {})", announce.peer_id, announce.listen_addrs.join(","));
                                            let mut valid_addrs = Vec::new();
                                            for addr_str in &announce.listen_addrs {
                                                if let Ok(ma) = libp2p::Multiaddr::from_str(addr_str) {
                                                    swarm.behaviour_mut().kademlia.add_address(&src, ma);
                                                    valid_addrs.push(addr_str.clone());
                                                }
                                            }
                                            peer_cache.add_or_update(&announce.peer_id, valid_addrs, false);
                                        }
                                    }
                                }
                            }
                        }
                    }
                    SwarmEvent::Behaviour(crate::network::StorageBehaviourEvent::ReqResp(event)) => {
                        match event {
                            request_response::Event::Message { peer: _peer, message } => {
                                match message {
                                    request_response::Message::Request { request, channel, .. } => {
                                        match request {
                                            DirectRequest::Handshake { challenge } => {
                                                // Simplified handshake response for now
                                                let _ = swarm.behaviour_mut().req_resp.send_response(channel, DirectResponse::HandshakeResponse(challenge.into_bytes()));
                                            }
                                            DirectRequest::StoreShard { chunk_key, data } => {
                                                let record = Record {
                                                    key: RecordKey::new(&chunk_key),
                                                    value: data,
                                                    publisher: None,
                                                    expires: None,
                                                };
                                                let _ = swarm.behaviour_mut().kademlia.store_mut().put(record);
                                                let _ = swarm.behaviour_mut().req_resp.send_response(channel, DirectResponse::StoreOk);
                                            }
                                            DirectRequest::FetchShard { chunk_key } => {
                                                let record_key = RecordKey::new(&chunk_key);
                                                let data = swarm.behaviour_mut().kademlia.store_mut().get(&record_key).map(|r| r.value.clone());
                                                let _ = swarm.behaviour_mut().req_resp.send_response(channel, DirectResponse::ShardData(data));
                                            }
                                            DirectRequest::FetchManifest { file_hash } => {
                                                let record_key = RecordKey::new(&format!("{}_manifest", file_hash));
                                                let data = swarm.behaviour_mut().kademlia.store_mut().get(&record_key).map(|r| r.value.clone());
                                                if let Some(val) = data {
                                                    if let Ok(manifest) = serde_json::from_slice::<Manifest>(&val) {
                                                        let _ = swarm.behaviour_mut().req_resp.send_response(channel, DirectResponse::ManifestData(Some(manifest)));
                                                    } else {
                                                        let _ = swarm.behaviour_mut().req_resp.send_response(channel, DirectResponse::ManifestData(None));
                                                    }
                                                } else {
                                                    let _ = swarm.behaviour_mut().req_resp.send_response(channel, DirectResponse::ManifestData(None));
                                                }
                                            }
                                        }
                                    }
                                    request_response::Message::Response { request_id, response } => {
                                        match response {
                                            DirectResponse::ShardData(Some(data)) => {
                                                if let Some((hash, index)) = req_resp_to_fetch.remove(&request_id) {
                                                    if let Some(state) = active_fetches.get_mut(&hash) {
                                                        if state.shards[index].is_none() {
                                                            state.shards[index] = Some(data);
                                                            state.received += 1;
                                                            if state.received >= DATA_SHARDS {
                                                                println!("Collected {}/45 shards for {} via ReqResp. Restoring...", DATA_SHARDS, hash);
                                                                if let Ok(decoded) = decode_data(state.shards.clone(), state.original_size) {
                                                                    if let Some(sender) = state.sender.take() {
                                                                        let _ = sender.send(Some(decoded));
                                                                    }
                                                                } else {
                                                                    // Trigger self-healing if decode fails but we got enough shards
                                                                    let local_peer_id = *swarm.local_peer_id();
                                                                    do_self_healing(&hash, state, &mut swarm, &peer_cache, local_peer_id);
                                                                    if let Some(sender) = state.sender.take() {
                                                                        let _ = sender.send(None);
                                                                    }
                                                                }
                                                                active_fetches.remove(&hash);
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                            DirectResponse::ShardData(None) => {
                                                if let Some((hash, _index)) = req_resp_to_fetch.remove(&request_id) {
                                                    if let Some(state) = active_fetches.get_mut(&hash) {
                                                        state.failed += 1;
                                                        if state.failed + state.received >= TOTAL_SHARDS {
                                                            println!("Fetch failed for {}: not enough shards (received: {}, failed: {})", hash, state.received, state.failed);
                                                            if let Some(sender) = state.sender.take() {
                                                                let _ = sender.send(None);
                                                            }
                                                            active_fetches.remove(&hash);
                                                        }
                                                    }
                                                }
                                            }
                                            _ => {}
                                        }
                                    }
                                }
                            }
                            request_response::Event::OutboundFailure { request_id, .. } => {
                                if let Some((hash, _index)) = req_resp_to_fetch.remove(&request_id) {
                                    if let Some(state) = active_fetches.get_mut(&hash) {
                                        state.failed += 1;
                                        if state.failed + state.received >= TOTAL_SHARDS {
                                            println!("Fetch failed for {}: not enough shards (received: {}, failed: {})", hash, state.received, state.failed);
                                            if let Some(sender) = state.sender.take() {
                                                let _ = sender.send(None);
                                            }
                                            active_fetches.remove(&hash);
                                        }
                                    }
                                }
                            }
                            _ => {}
                        }
                    }
                    _ => {}
                }
            }
            Some(command) = command_rx.recv() => {
                match command {
                    SwarmCommand::DhtUpload(data, storage_class, did, reply) => {
                        let mut hasher = Sha256::new();
                        hasher.update(&data);
                        let hash = hex::encode(hasher.finalize());
                        println!("Uploading file, hash: {}, size: {} bytes, class: {}", hash, data.len(), storage_class);

                        match encode_data(&data) {
                            Ok(shards) => {
                                let mut manifest = Manifest {
                                    file_hash: hash.clone(),
                                    size: data.len(),
                                    storage_class: Some(storage_class.as_str().to_string()),
                                    shards: HashMap::new(),
                                };
                                
                                let top_peers = peer_cache.top_n_addrs(45);
                                let mut target_peers = Vec::new();
                                for addr_str in top_peers {
                                    if let Ok(ma) = libp2p::Multiaddr::from_str(&addr_str) {
                                        for p in ma.iter() {
                                            if let libp2p::multiaddr::Protocol::P2p(mh) = p {
                                                if let Ok(pid) = PeerId::from_multihash(mh.into()) {
                                                    target_peers.push(pid);
                                                    break;
                                                }
                                            }
                                        }
                                    }
                                }
                                if target_peers.is_empty() {
                                    target_peers.push(*swarm.local_peer_id());
                                }

                                for (i, shard) in shards.iter().enumerate() {
                                    let chunk_key = format!("{}_chunk_{}", hash, i);
                                    let target_peer = target_peers[i % target_peers.len()];
                                    manifest.shards.insert(i, target_peer.to_string());
                                    
                                    if target_peer != *swarm.local_peer_id() {
                                        let _ = swarm.behaviour_mut().req_resp.send_request(
                                            &target_peer,
                                            DirectRequest::StoreShard { chunk_key: chunk_key.clone(), data: shard.clone() }
                                        );
                                    } else {
                                        let record = Record {
                                            key: RecordKey::new(&chunk_key),
                                            value: shard.clone(),
                                            publisher: None,
                                            expires: None,
                                        };
                                        let _ = swarm.behaviour_mut().kademlia.put_record(record, libp2p::kad::Quorum::One);
                                    }
                                }

                                if let Ok(manifest_bytes) = serde_json::to_vec(&manifest) {
                                    let manifest_record = Record {
                                        key: RecordKey::new(&format!("{}_manifest", hash)),
                                        value: manifest_bytes,
                                        publisher: None,
                                        expires: None,
                                    };
                                    let _ = swarm.behaviour_mut().kademlia.put_record(manifest_record, libp2p::kad::Quorum::One);
                                }
                                let _ = reply.send(hash);
                            },
                            Err(e) => {
                                // Release quota reservation (global + network-wide per-user) on encoding failure
                                quota_manager.release(storage_class, data.len() as u64);
                                crate::release_storage_on_consensus(&did, data.len() as u64).await;
                                println!("Error encoding data: {:?}", e);
                                let _ = reply.send("error".to_string());
                            }
                        }
                    }
                    SwarmCommand::DhtDownload(hash, reply) => {
                        println!("DhtDownload requested for: {}", hash);
                        
                        let manifest_key = RecordKey::new(&format!("{}_manifest", hash));
                        // 1. Check local store
                        if let Some(record) = swarm.behaviour_mut().kademlia.store_mut().get(&manifest_key) {
                            if let Ok(manifest) = serde_json::from_slice::<Manifest>(&record.value) {
                                println!("Found manifest locally for {}", hash);
                                let mut fetch_state = FetchState {
                                    sender: Some(reply),
                                    shards: vec![None; TOTAL_SHARDS],
                                    received: 0,
                                    failed: 0,
                                    original_size: manifest.size,
                                    manifest: Some(manifest.clone()),
                                };
                                
                                for (index, peer_id_str) in manifest.shards {
                                    if let Ok(peer_id) = PeerId::from_str(&peer_id_str) {
                                        if peer_id == *swarm.local_peer_id() {
                                            let chunk_key = RecordKey::new(&format!("{}_chunk_{}", hash, index));
                                            if let Some(chunk_rec) = swarm.behaviour_mut().kademlia.store_mut().get(&chunk_key) {
                                                fetch_state.shards[index] = Some(chunk_rec.value.clone());
                                                fetch_state.received += 1;
                                            }
                                        } else {
                                            let chunk_key = format!("{}_chunk_{}", hash, index);
                                            let req_id = swarm.behaviour_mut().req_resp.send_request(
                                                &peer_id,
                                                DirectRequest::FetchShard { chunk_key }
                                            );
                                            req_resp_to_fetch.insert(req_id, (hash.clone(), index));
                                        }
                                    }
                                }
                                
                                if fetch_state.received >= DATA_SHARDS {
                                    if let Ok(decoded) = decode_data(fetch_state.shards.clone(), fetch_state.original_size) {
                                        if let Some(sender) = fetch_state.sender.take() {
                                            let _ = sender.send(Some(decoded));
                                        }
                                    }
                                } else {
                                    active_fetches.insert(hash.clone(), fetch_state);
                                }
                                continue;
                            }
                        }
                        
                        // 2. Fetch from Kademlia
                        println!("Manifest not local. Querying DHT for {}", hash);
                        let qid = swarm.behaviour_mut().kademlia.get_record(manifest_key);
                        manifest_queries.insert(qid, hash.clone());
                        
                        active_fetches.insert(hash.clone(), FetchState {
                            sender: Some(reply),
                            shards: vec![None; TOTAL_SHARDS],
                            received: 0,
                            failed: 0,
                            original_size: 0,
                            manifest: None,
                        });
                    }
                    SwarmCommand::DhtDelete(hash, reply) => {
                        println!("Deleting file from local storage: {}", hash);
                        let manifest_key = RecordKey::new(&format!("{}_manifest", hash));
                        let mut deleted_size: Option<u64> = None;
                        if let Some(record) = swarm.behaviour_mut().kademlia.store_mut().get(&manifest_key) {
                            if let Ok(manifest) = serde_json::from_slice::<Manifest>(&record.value) {
                                deleted_size = Some(manifest.size as u64);
                                for index in manifest.shards.keys() {
                                    let chunk_key = RecordKey::new(&format!("{}_chunk_{}", hash, index));
                                    swarm.behaviour_mut().kademlia.remove_record(&chunk_key);
                                }
                            }
                        }
                        swarm.behaviour_mut().kademlia.remove_record(&manifest_key);
                        let _ = reply.send(deleted_size);
                    }
                    SwarmCommand::SavePeerCache => {
                        peer_cache.save(peer_cache_path);
                    }
                    SwarmCommand::GcPeerCache(days) => {
                        peer_cache.gc(days);
                    }
                    SwarmCommand::AnnouncePeer => {
                        let listen_addrs: Vec<String> = swarm.listeners().map(|a| a.to_string()).collect();
                        let pubkey_bytes = local_key.public().encode_protobuf();
                        if !pubkey_bytes.is_empty() {
                            use base64::{Engine as _, engine::general_purpose};
                            let pubkey_b64 = general_purpose::STANDARD.encode(&pubkey_bytes);
                            let current_storage_full = storage_full.load(std::sync::atomic::Ordering::Relaxed);
                            let storage_status = if current_storage_full { "Full".to_string() } else { "OK".to_string() };
                            // Phase 1: Include per-class quota status in announcements
                            let quota_snapshot = quota_manager.usage_all();
                            let mut announce = PeerAnnounce {
                                peer_id: swarm.local_peer_id().to_string(),
                                listen_addrs,
                                timestamp: std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs(),
                                nonce: None,
                                signature: None,
                                public_key: Some(pubkey_b64),
                                storage_status: Some(storage_status),
                                quota_status: Some(quota_snapshot),
                                is_supernode: Some(false),
                                api_url: Some(http_url.clone()),
                            };

                            if let Ok(payload) = serde_json::to_vec(&announce) {
                                if let Ok(sig) = local_key.sign(&payload) {
                                    announce.signature = Some(hex::encode(sig));
                                    if let Ok(final_payload) = serde_json::to_vec(&announce) {
                                        let announce_topic = libp2p::gossipsub::IdentTopic::new("storage_announcements");
                                        println!("Publishing announce, size: {}", final_payload.len());
                                        let _ = swarm.behaviour_mut().gossipsub.publish(announce_topic, final_payload);
                                    }
                                }
                            }
                        }
                    }
                    SwarmCommand::Publish(topic_name, data) => {
                        println!("Publishing to {}, size: {} bytes", topic_name, data.len());
                        let topic = libp2p::gossipsub::IdentTopic::new(topic_name);
                        if let Err(e) = swarm.behaviour_mut().gossipsub.publish(topic, data) {
                            if let libp2p::gossipsub::PublishError::InsufficientPeers = e {
                                // Ігноруємо, оскільки це нормально при старті ноди або малій кількості пірів
                            } else {
                                println!("Failed to publish message: {:?}", e);
                            }
                        }
                    }
                    SwarmCommand::SubscribeTopic(topic_name) => {
                        let topic = libp2p::gossipsub::IdentTopic::new(topic_name);
                        if let Err(e) = swarm.behaviour_mut().gossipsub.subscribe(&topic) {
                            println!("Failed to subscribe to topic: {:?}", e);
                        }
                    }
                }
            }
        }
    }
}

