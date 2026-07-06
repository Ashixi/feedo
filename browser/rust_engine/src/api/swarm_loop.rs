use crate::api::network::{StorageBehaviour, DirectRequest, DirectResponse, Manifest, encode_data, decode_data, DATA_SHARDS, PARITY_SHARDS, TOTAL_SHARDS, StorageBehaviourEvent};
use libp2p::swarm::SwarmEvent;
use libp2p::Swarm;
use tokio::sync::{mpsc, oneshot};
use futures::StreamExt;
use std::collections::HashMap;
use std::str::FromStr;
use libp2p::kad::RecordKey;
use libp2p::request_response;
use libp2p::PeerId;

pub struct FetchState {
    pub sender: Option<oneshot::Sender<Option<Vec<u8>>>>,
    pub shards: Vec<Option<Vec<u8>>>,
    pub received: usize,
    pub original_size: usize,
    pub manifest: Option<Manifest>,
}

pub enum SwarmCommand {
    DhtFetchFile(String, oneshot::Sender<Option<Vec<u8>>>),
}

pub async fn run_swarm(
    mut swarm: Swarm<StorageBehaviour>,
    mut command_rx: mpsc::UnboundedReceiver<SwarmCommand>,
) {
    let mut active_fetches: HashMap<String, FetchState> = HashMap::new();
    let mut manifest_queries: HashMap<libp2p::kad::QueryId, String> = HashMap::new();
    let mut query_to_fetch: HashMap<libp2p::kad::QueryId, (String, usize)> = HashMap::new();
    let mut req_resp_to_fetch: HashMap<request_response::OutboundRequestId, (String, usize)> = HashMap::new();

    loop {
        tokio::select! {
            Some(cmd) = command_rx.recv() => {
                match cmd {
                    SwarmCommand::DhtFetchFile(hash, sender) => {
                        println!("Starting DHT fetch for {}", hash);
                        let query_id = swarm.behaviour_mut().kademlia.get_record(RecordKey::new(&format!("{}_manifest", hash)));
                        manifest_queries.insert(query_id, hash.clone());
                        
                        active_fetches.insert(hash.clone(), FetchState {
                            sender: Some(sender),
                            shards: vec![None; TOTAL_SHARDS],
                            received: 0,
                            original_size: 0,
                            manifest: None,
                        });
                    }
                }
            }
            event = swarm.select_next_some() => {
                match event {
                    SwarmEvent::NewListenAddr { address, .. } => {
                        println!("Listening on P2P address: {}", address);
                    }
                    SwarmEvent::ConnectionEstablished { peer_id, endpoint, .. } => {
                        println!("Connection established with {}", peer_id);
                        if endpoint.is_dialer() {
                            swarm.behaviour_mut().kademlia.add_address(&peer_id, endpoint.get_remote_address().clone());
                            let _ = swarm.behaviour_mut().kademlia.bootstrap();
                        }
                    }
                    SwarmEvent::Behaviour(StorageBehaviourEvent::Kademlia(libp2p::kad::Event::OutboundQueryProgressed { id, result, .. })) => {
                        if let libp2p::kad::QueryResult::GetRecord(Ok(libp2p::kad::GetRecordOk::FoundRecord(record))) = result {
                            if let Some(hash) = manifest_queries.remove(&id) {
                                if let Ok(manifest) = serde_json::from_slice::<Manifest>(&record.record.value) {
                                    println!("Manifest received from DHT for {}. Starting parallel shard download...", hash);
                                    if let Some(state) = active_fetches.get_mut(&hash) {
                                        state.manifest = Some(manifest.clone());
                                        state.original_size = manifest.size;
                                    }
                                    for (index, peer_id_str) in manifest.shards.iter() {
                                        if let Ok(peer_id) = PeerId::from_str(peer_id_str) {
                                            let chunk_key = format!("{}_chunk_{}", hash, index);
                                            let req_id = swarm.behaviour_mut().req_resp.send_request(
                                                &peer_id,
                                                DirectRequest::FetchShard { chunk_key }
                                            );
                                            req_resp_to_fetch.insert(req_id, (hash.clone(), *index));
                                        }
                                    }
                                }
                            } else if let Some((hash, index)) = query_to_fetch.remove(&id) {
                                if let Some(state) = active_fetches.get_mut(&hash) {
                                    if state.shards[index].is_none() {
                                        state.shards[index] = Some(record.record.value);
                                        state.received += 1;
                                        if state.received >= DATA_SHARDS {
                                            println!("Collected {}/{} shards for {} via DHT. Restoring...", state.received, DATA_SHARDS, hash);
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
                        } else if let libp2p::kad::QueryResult::GetRecord(Err(e)) = result {
                            if let Some(hash) = manifest_queries.remove(&id) {
                                println!("Failed to find manifest for {}: {:?}", hash, e);
                                if let Some(mut state) = active_fetches.remove(&hash) {
                                    if let Some(sender) = state.sender.take() {
                                        let _ = sender.send(None);
                                    }
                                }
                            }
                        }
                    }
                    SwarmEvent::Behaviour(StorageBehaviourEvent::ReqResp(request_response::Event::Message { peer, message })) => {
                        if let request_response::Message::Response { request_id, response } = message {
                            if let Some((hash, index)) = req_resp_to_fetch.remove(&request_id) {
                                if let DirectResponse::ShardData(Some(data)) = response {
                                    if let Some(state) = active_fetches.get_mut(&hash) {
                                        if state.shards[index].is_none() {
                                            state.shards[index] = Some(data);
                                            state.received += 1;
                                            println!("Received chunk {} for {}. Total: {}/{}", index, hash, state.received, DATA_SHARDS);
                                            if state.received >= DATA_SHARDS {
                                                println!("Collected {}/{} shards for {} via Direct. Restoring...", state.received, DATA_SHARDS, hash);
                                                if let Ok(decoded) = decode_data(state.shards.clone(), state.original_size) {
                                                    if let Some(sender) = state.sender.take() {
                                                        let _ = sender.send(Some(decoded));
                                                    }
                                                }
                                                active_fetches.remove(&hash);
                                            }
                                        }
                                    }
                                } else {
                                    println!("Peer {} didn't have chunk {}, falling back to DHT...", peer, index);
                                    let chunk_key = format!("{}_chunk_{}", hash, index);
                                    let query_id = swarm.behaviour_mut().kademlia.get_record(RecordKey::new(&chunk_key));
                                    query_to_fetch.insert(query_id, (hash, index));
                                }
                            }
                        }
                    }
                    _ => {}
                }
            }
        }
    }
}
