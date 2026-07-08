use crate::network::{ConsensusBehaviour, ConsensusBehaviourEvent};
use libp2p::swarm::SwarmEvent;
use libp2p::Swarm;
use tokio::sync::mpsc;
use futures::StreamExt;
use std::sync::Arc;
use tokio::sync::Mutex;
use shared_proto::feedo::PbftMessage;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Announcement message published on "feedo_peer_announce" gossipsub topic.
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct PeerAnnounce {
    pub peer_id: String,
    pub wallet_address: String,
    pub reputation: u64,
    pub version: String,
}

/// Reputation record stored in DHT under "/reputation/{wallet_address}"
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct ReputationRecord {
    pub reputation: u64,
    pub updated_at: u64,
}

pub enum SwarmCommand {
    PublishPpor(PbftMessage),
    /// Relays a transaction to the 21 validators via request-response (replaces gossipsub broadcast).
    RelayTxToValidators {
        tx_type: i32,
        tx_data_json: String,
        from_node: String,
        signature: String,
    },
    // Legacy broadcast commands — kept for backward compatibility during transition.
    BroadcastNameTx(crate::NameRegistrationTx),
    BroadcastUpdateCidTx(crate::UpdateCidTx),
    BroadcastLedgerTx(crate::LedgerTx),
    PublishDidDht(String, crate::did::DidDocument),
    PublishDht(String, crate::ResolveRes),
    LookupDht(String, tokio::sync::oneshot::Sender<Option<crate::ResolveRes>>),
    LookupDidDht(String, tokio::sync::oneshot::Sender<Option<crate::did::DidDocument>>),
    PublishReputationDht(String, u64), // wallet_address, reputation_score
}

pub async fn run_swarm(
    mut swarm: Swarm<ConsensusBehaviour>,
    mut command_rx: mpsc::UnboundedReceiver<SwarmCommand>,
    ppor_manager: Arc<Mutex<crate::ppor::PporManager>>,
    name_db: Arc<Mutex<crate::name_db::NameDb>>,
    _did_manager: Arc<Mutex<crate::did::DidManager>>,
    ledger: Arc<crate::accounting::Ledger>,
) {
    let mut pending_queries: HashMap<libp2p::kad::QueryId, tokio::sync::oneshot::Sender<Option<crate::ResolveRes>>> = HashMap::new();
    let mut pending_did_queries: HashMap<libp2p::kad::QueryId, tokio::sync::oneshot::Sender<Option<crate::did::DidDocument>>> = HashMap::new();
    let mut pending_name_txs: HashMap<String, crate::NameRegistrationTx> = HashMap::new();
    let mut pending_cid_txs: HashMap<String, crate::UpdateCidTx> = HashMap::new();
    let mut pending_ledger_txs: HashMap<String, crate::LedgerTx> = HashMap::new();
    // Maps wallet_address -> PeerId (populated via peer_announce + identify)
    let mut wallet_to_peer: HashMap<String, libp2p::PeerId> = HashMap::new();
    // Maps PeerId -> wallet_address (for reverse lookup)
    let mut peer_to_wallet: HashMap<libp2p::PeerId, String> = HashMap::new();

    // --- Publish our own announcement on startup ---
    {
        let manager = ppor_manager.lock().await;
        let my_peer_id = swarm.local_peer_id().to_string();
        let my_wallet = manager.node_id.clone();
        let my_reputation = manager.reputation_table.get(&my_wallet).copied().unwrap_or(10);
        let announce = PeerAnnounce {
            peer_id: my_peer_id.clone(), // clone before move
            wallet_address: my_wallet.clone(),
            reputation: my_reputation,
            version: "1.0.0".to_string(),
        };
        eprintln!("[BOOTSTRAP] Published self-announce: wallet={}, peer={}", my_wallet, my_peer_id);
        if let Ok(data) = serde_json::to_vec(&announce) {
            let topic = libp2p::gossipsub::IdentTopic::new("feedo_peer_announce");
            let _ = swarm.behaviour_mut().gossipsub.publish(topic, data);
        }
        // Also publish initial reputation to DHT
        let rep_record = ReputationRecord {
            reputation: my_reputation,
            updated_at: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs(),
        };
        let rep_key = format!("/reputation/{}", my_wallet);
        if let Ok(value) = serde_json::to_vec(&rep_record) {
            let record = libp2p::kad::Record {
                key: libp2p::kad::RecordKey::new(&rep_key),
                value,
                publisher: None,
                expires: None,
            };
            let _ = swarm.behaviour_mut().kademlia.put_record(record, libp2p::kad::Quorum::One);
        }
    }

    loop {
        tokio::select! {
            event = swarm.select_next_some() => {
                match event {
                    SwarmEvent::NewListenAddr { address, .. } => {
                        eprintln!("Consensus node listening on P2P address: {}", address);
                    }
                    SwarmEvent::ConnectionEstablished { peer_id, .. } => {
                        eprintln!("Consensus connected to {}", peer_id);
                    }
                    SwarmEvent::Behaviour(ConsensusBehaviourEvent::Identify(libp2p::identify::Event::Received { peer_id, info, .. })) => {
                        eprintln!("[IDENTIFY] Received from {}: protocol={}", peer_id, info.protocol_version);
                    }
                    // --- Handle incoming transaction via request-response (Step 16) ---
                    SwarmEvent::Behaviour(ConsensusBehaviourEvent::RequestResponse(
                        libp2p::request_response::Event::Message { peer: _, message }
                    )) => {
                        match message {
                            libp2p::request_response::Message::Request { request_id: _, request, channel } => {
                                eprintln!("[TX_RELAY] Received transaction from {}: type={}", request.from_node, request.tx_type);
                                // Validate and start PBFT
                                let tx_hash = {
                                    use sha2::{Sha256, Digest};
                                    let mut hasher = Sha256::new();
                                    hasher.update(format!("{}{}{}", request.tx_type, request.tx_data_json, request.from_node));
                                    hex::encode(hasher.finalize())
                                };

                                let mut manager = ppor_manager.lock().await;
                                let tx_type: i32 = request.tx_type.parse().unwrap_or(0);
                                if let Some(reply_msg) = manager.propose(tx_hash.clone(), 0, tx_type) {
                                    // Broadcast PBFT message via gossipsub
                                    let data = prost::Message::encode_to_vec(&reply_msg);
                                    let topic = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                    let _ = swarm.behaviour_mut().gossipsub.publish(topic, data);

                                    // Also process locally
                                    if let Ok(tx_data) = serde_json::from_str::<serde_json::Value>(&request.tx_data_json) {
                                        if tx_type == crate::ppor::TX_TYPE_NAME_REGISTRATION {
                                            if let Ok(tx) = serde_json::from_value::<crate::NameRegistrationTx>(tx_data) {
                                                pending_name_txs.insert(tx_hash.clone(), tx);
                                            }
                                        } else if tx_type == crate::ppor::TX_TYPE_UPDATE_CID {
                                            if let Ok(tx) = serde_json::from_value::<crate::UpdateCidTx>(tx_data) {
                                                pending_cid_txs.insert(tx_hash.clone(), tx);
                                            }
                                        } else if tx_type == crate::ppor::TX_TYPE_LEDGER {
                                            if let Ok(tx) = serde_json::from_value::<crate::LedgerTx>(tx_data) {
                                                pending_ledger_txs.insert(tx_hash.clone(), tx);
                                            }
                                        }
                                    }
                                }

                                // Send response back
                                let response = crate::network::TxResponse {
                                    accepted: true,
                                    reason: "ok".to_string(),
                                };
                                let _ = swarm.behaviour_mut().request_response.send_response(channel, response);
                            }
                            libp2p::request_response::Message::Response { request_id: _, response } => {
                                eprintln!("[TX_RELAY] Got response from validator: accepted={}", response.accepted);
                            }
                        }
                    }
                    SwarmEvent::Behaviour(ConsensusBehaviourEvent::Gossipsub(libp2p::gossipsub::Event::Message { message, .. })) => {
                        let topic = message.topic.as_str();
                        if topic == "feedo_peer_announce" {
                            if let Ok(announce) = serde_json::from_slice::<PeerAnnounce>(&message.data) {
                                eprintln!("[PEER_ANNOUNCE] Received: wallet={}, peer={}, rep={}",
                                    announce.wallet_address, announce.peer_id, announce.reputation);
                                if let Ok(peer_id) = announce.peer_id.parse::<libp2p::PeerId>() {
                                    wallet_to_peer.insert(announce.wallet_address.clone(), peer_id);
                                    peer_to_wallet.insert(peer_id, announce.wallet_address.clone());
                                }
                                let mut manager = ppor_manager.lock().await;
                                if !manager.reputation_table.contains_key(&announce.wallet_address) {
                                    manager.reputation_table.insert(announce.wallet_address.clone(), announce.reputation);
                                    eprintln!("[REPUTATION] Added new node {} with score {}", announce.wallet_address, announce.reputation);
                                }
                                // Immediately recalculate committee to include the new node
                                let seed = format!("{}:{}", manager.last_finalized_hash, manager.current_epoch);
                                manager.select_committee_weighted(&seed);
                            }
                        } else if topic == "feedo_consensus_ppor" {
                            if let Ok(pbft_msg) = <shared_proto::feedo::PbftMessage as prost::Message>::decode(&message.data[..]) {
                                let mut manager = ppor_manager.lock().await;
                                let reply_msg = manager.handle_message(pbft_msg.clone());
                                if let Some(ref reply) = reply_msg {
                                    let data = prost::Message::encode_to_vec(reply);
                                    let topic = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                    let _ = swarm.behaviour_mut().gossipsub.publish(topic, data);
                                }
                                // Process locally since gossipsub doesn't deliver to self — chain next phases
                                let reply_msg2 = reply_msg.and_then(|r| manager.handle_message(r));
                                if let Some(ref reply2) = reply_msg2 {
                                    let data2 = prost::Message::encode_to_vec(reply2);
                                    let topic2 = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                    let _ = swarm.behaviour_mut().gossipsub.publish(topic2, data2);
                                }
                                let _reply_msg3 = reply_msg2.and_then(|r| manager.handle_message(r));
                                if let Some(ref reply3) = _reply_msg3 {
                                    let data3 = prost::Message::encode_to_vec(reply3);
                                    let topic3 = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                    let _ = swarm.behaviour_mut().gossipsub.publish(topic3, data3);
                                }
                                if pbft_msg.phase == shared_proto::feedo::PbftPhase::Finalized as i32 {
                                    if pbft_msg.tx_type == crate::ppor::TX_TYPE_NAME_REGISTRATION {
                                        if let Some(tx) = pending_name_txs.remove(&pbft_msg.tx_hash) {
                                            if ledger.debit(&tx.did, 100).await {
                                                let db = name_db.lock().await;
                                                let _ = db.insert_name(&tx.name, &tx.did, &tx.public_key);
                                                eprintln!("Decentralized Name FINALIZED: {}", tx.name);
                                                let finalized_at = std::time::SystemTime::now()
                                                    .duration_since(std::time::UNIX_EPOCH)
                                                    .unwrap()
                                                    .as_secs();
                                                let epoch = manager.current_epoch;
                                                let res = crate::ResolveRes {
                                                    did: tx.did,
                                                    cid: None,
                                                    gateways: None,
                                                    epoch: Some(epoch),
                                                    finalized_at: Some(finalized_at),
                                                };
                                                let record = libp2p::kad::Record {
                                                    key: libp2p::kad::RecordKey::new(&tx.name),
                                                    value: serde_json::to_vec(&res).unwrap(),
                                                    publisher: None,
                                                    expires: None,
                                                };
                                                let _ = swarm.behaviour_mut().kademlia.put_record(record, libp2p::kad::Quorum::One);
                                                // Remove PporState after Finalized (Step 21)
                                                manager.states.remove(&pbft_msg.tx_hash);
                                            }
                                        }
                                    } else if pbft_msg.tx_type == crate::ppor::TX_TYPE_UPDATE_CID {
                                        if let Some(tx) = pending_cid_txs.remove(&pbft_msg.tx_hash) {
                                            let db = name_db.lock().await;
                                            if let Ok(Some((did, _, _))) = db.resolve_name(&tx.name) {
                                                let gateways_json = serde_json::to_string(&tx.gateways).unwrap_or_else(|_| "[]".to_string());
                                                let _ = db.update_cid(&tx.name, &tx.cid, &gateways_json);
                                                eprintln!("Decentralized CID UPDATE FINALIZED: {} -> {}", tx.name, tx.cid);
                                                let finalized_at = std::time::SystemTime::now()
                                                    .duration_since(std::time::UNIX_EPOCH)
                                                    .unwrap()
                                                    .as_secs();
                                                let epoch = manager.current_epoch;
                                                let res = crate::ResolveRes {
                                                    did,
                                                    cid: Some(tx.cid),
                                                    gateways: Some(tx.gateways),
                                                    epoch: Some(epoch),
                                                    finalized_at: Some(finalized_at),
                                                };
                                                let record = libp2p::kad::Record {
                                                    key: libp2p::kad::RecordKey::new(&tx.name),
                                                    value: serde_json::to_vec(&res).unwrap(),
                                                    publisher: None,
                                                    expires: None,
                                                };
                                                let _ = swarm.behaviour_mut().kademlia.put_record(record, libp2p::kad::Quorum::One);
                                                // Remove PporState after Finalized (Step 21)
                                                manager.states.remove(&pbft_msg.tx_hash);
                                            }
                                        }
                                    } else if pbft_msg.tx_type == crate::ppor::TX_TYPE_LEDGER {
                                        if let Some(tx) = pending_ledger_txs.remove(&pbft_msg.tx_hash) {
                                            if tx.is_credit {
                                                ledger.credit(&tx.did, tx.amount).await;
                                                eprintln!("Decentralized Ledger CREDIT FINALIZED: {} for {}", tx.amount, tx.did);
                                            } else {
                                                let _ = ledger.debit(&tx.did, tx.amount).await;
                                                eprintln!("Decentralized Ledger DEBIT FINALIZED: {} from {}", tx.amount, tx.did);
                                            }
                                        }
                                    }
                                }
                            }
                        } else if topic == "feedo_name_txs" {
                            if let Ok(tx) = serde_json::from_slice::<crate::NameRegistrationTx>(&message.data) {
                                let payload_bytes = format!("{}{}", tx.name, tx.did).into_bytes();
                                if crate::did::verify_signature(&tx.public_key, &payload_bytes, &tx.signature) {
                                    let hash = tx.tx_hash();
                                    pending_name_txs.insert(hash.clone(), tx);
                                    let mut manager = ppor_manager.lock().await;
                                    let reply_msg = manager.mark_validated(&hash, crate::ppor::TX_TYPE_NAME_REGISTRATION);
                                    if let Some(ref reply) = reply_msg {
                                        let data = prost::Message::encode_to_vec(reply);
                                        let topic = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                        let _ = swarm.behaviour_mut().gossipsub.publish(topic, data);
                                    }
                                    // Self-deliver for self-committee: gossipsub doesn't deliver to self
                                    let reply_msg2 = reply_msg.and_then(|r| manager.handle_message(r));
                                    if let Some(ref reply2) = reply_msg2 {
                                        let data2 = prost::Message::encode_to_vec(reply2);
                                        let topic2 = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                        let _ = swarm.behaviour_mut().gossipsub.publish(topic2, data2);
                                    }
                                    let reply_msg3 = reply_msg2.and_then(|r| manager.handle_message(r));
                                    if let Some(ref reply3) = reply_msg3 {
                                        let data3 = prost::Message::encode_to_vec(reply3);
                                        let topic3 = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                        let _ = swarm.behaviour_mut().gossipsub.publish(topic3, data3);
                                    }
                                }
                            }
                        } else if topic == "feedo_update_cid_txs" {
                            if let Ok(tx) = serde_json::from_slice::<crate::UpdateCidTx>(&message.data) {
                                let hash = tx.tx_hash();
                                pending_cid_txs.insert(hash.clone(), tx);
                                let mut manager = ppor_manager.lock().await;
                                let reply_msg = manager.mark_validated(&hash, crate::ppor::TX_TYPE_UPDATE_CID);
                                if let Some(ref reply) = reply_msg {
                                    let data = prost::Message::encode_to_vec(reply);
                                    let topic = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                    let _ = swarm.behaviour_mut().gossipsub.publish(topic, data);
                                }
                                // Self-deliver for self-committee: gossipsub doesn't deliver to self
                                let reply_msg2 = reply_msg.and_then(|r| manager.handle_message(r));
                                if let Some(ref reply2) = reply_msg2 {
                                    let data2 = prost::Message::encode_to_vec(reply2);
                                    let topic2 = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                    let _ = swarm.behaviour_mut().gossipsub.publish(topic2, data2);
                                }
                                let reply_msg3 = reply_msg2.and_then(|r| manager.handle_message(r));
                                if let Some(ref reply3) = reply_msg3 {
                                    let data3 = prost::Message::encode_to_vec(reply3);
                                    let topic3 = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                    let _ = swarm.behaviour_mut().gossipsub.publish(topic3, data3);
                                }
                            }
                        } else if topic == "feedo_ledger_txs" {
                            if let Ok(tx) = serde_json::from_slice::<crate::LedgerTx>(&message.data) {
                                let hash = tx.tx_hash();
                                pending_ledger_txs.insert(hash.clone(), tx);
                                let mut manager = ppor_manager.lock().await;
                                let reply_msg = manager.mark_validated(&hash, crate::ppor::TX_TYPE_LEDGER);
                                if let Some(ref reply) = reply_msg {
                                    let data = prost::Message::encode_to_vec(reply);
                                    let topic = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                    let _ = swarm.behaviour_mut().gossipsub.publish(topic, data);
                                }
                                // Self-deliver for self-committee: gossipsub doesn't deliver to self
                                let reply_msg2 = reply_msg.and_then(|r| manager.handle_message(r));
                                if let Some(ref reply2) = reply_msg2 {
                                    let data2 = prost::Message::encode_to_vec(reply2);
                                    let topic2 = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                    let _ = swarm.behaviour_mut().gossipsub.publish(topic2, data2);
                                }
                                let reply_msg3 = reply_msg2.and_then(|r| manager.handle_message(r));
                                if let Some(ref reply3) = reply_msg3 {
                                    let data3 = prost::Message::encode_to_vec(reply3);
                                    let topic3 = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                    let _ = swarm.behaviour_mut().gossipsub.publish(topic3, data3);
                                }
                            }
                        }
                    }
                    SwarmEvent::Behaviour(ConsensusBehaviourEvent::Kademlia(event)) => {
                        match event {
                            libp2p::kad::Event::RoutingUpdated { peer, is_new_peer, .. } => {
                                if is_new_peer {
                                    eprintln!("Consensus Kademlia DHT discovered a new node: {}", peer);
                                }
                            }
                            libp2p::kad::Event::OutboundQueryProgressed { id, result, .. } => {
                                // Пытаемся обработать pending name queries
                                if let Some(tx) = pending_queries.remove(&id) {
                                    let found = match &result {
                                        libp2p::kad::QueryResult::GetRecord(Ok(libp2p::kad::GetRecordOk::FoundRecord(peer_record))) => {
                                            serde_json::from_slice::<crate::ResolveRes>(&peer_record.record.value).ok()
                                        }
                                        _ => None,
                                    };
                                    let _ = tx.send(found);
                                }
                                // Пытаемся обработать pending DID queries
                                if let Some(tx) = pending_did_queries.remove(&id) {
                                    let found = match &result {
                                        libp2p::kad::QueryResult::GetRecord(Ok(libp2p::kad::GetRecordOk::FoundRecord(peer_record))) => {
                                            serde_json::from_slice::<crate::did::DidDocument>(&peer_record.record.value).ok()
                                        }
                                        _ => None,
                                    };
                                    let _ = tx.send(found);
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
                    SwarmCommand::PublishPpor(msg) => {
                        let data = prost::Message::encode_to_vec(&msg);
                        let topic = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                        if let Err(e) = swarm.behaviour_mut().gossipsub.publish(topic, data) {
                            eprintln!("Failed to publish PPoR message: {:?}", e);
                        }
                    }
                    SwarmCommand::BroadcastNameTx(tx) => {
                        // Still broadcast via gossipsub for backward compat
                        if let Ok(data) = serde_json::to_vec(&tx) {
                            let topic = libp2p::gossipsub::IdentTopic::new("feedo_name_txs");
                            if let Err(e) = swarm.behaviour_mut().gossipsub.publish(topic, data) {
                                eprintln!("Failed to publish NameRegistrationTx: {:?}", e);
                            }
                        }
                    }
                    SwarmCommand::BroadcastUpdateCidTx(tx) => {
                        if let Ok(data) = serde_json::to_vec(&tx) {
                            let topic = libp2p::gossipsub::IdentTopic::new("feedo_update_cid_txs");
                            if let Err(e) = swarm.behaviour_mut().gossipsub.publish(topic, data) {
                                eprintln!("Failed to publish UpdateCidTx: {:?}", e);
                            }
                        }
                    }
                    SwarmCommand::BroadcastLedgerTx(tx) => {
                        if let Ok(data) = serde_json::to_vec(&tx) {
                            let topic = libp2p::gossipsub::IdentTopic::new("feedo_ledger_txs");
                            if let Err(e) = swarm.behaviour_mut().gossipsub.publish(topic, data) {
                                eprintln!("Failed to publish LedgerTx: {:?}", e);
                            }
                        }
                    }
                    SwarmCommand::RelayTxToValidators { tx_type, tx_data_json, from_node, signature } => {
                        // Step 15: Send transaction to current validators via request-response
                        let manager = ppor_manager.lock().await;
                        let committee = manager.current_committee.clone();
                        let my_wallet = manager.node_id.clone();
                        drop(manager);

                        let tx_request = crate::network::TxRequest {
                            tx_type: tx_type.to_string(),
                            tx_data_json,
                            from_node: from_node.clone(),
                            signature,
                        };

                        let mut sent_count = 0u32;
                        for validator_wallet in &committee {
                            if *validator_wallet == my_wallet {
                                // Don't send to self — we process locally
                                continue;
                            }
                            if let Some(&peer_id) = wallet_to_peer.get(validator_wallet) {
                                let _ = swarm.behaviour_mut().request_response.send_request(&peer_id, tx_request.clone());
                                sent_count += 1;
                                eprintln!("[TX_RELAY] Sent to validator {} (peer={})", validator_wallet, peer_id);
                            }
                        }
                        if sent_count > 0 {
                            eprintln!("[TX_RELAY] Transaction relayed to {} validators", sent_count);
                        }
                    }
                    SwarmCommand::PublishDidDht(did, doc) => {
                        let record = libp2p::kad::Record {
                            key: libp2p::kad::RecordKey::new(&did),
                            value: serde_json::to_vec(&doc).unwrap(),
                            publisher: None,
                            expires: None,
                        };
                        let _ = swarm.behaviour_mut().kademlia.put_record(record, libp2p::kad::Quorum::One);
                        eprintln!("Published DID {} to Kademlia DHT", did);
                    }
                    SwarmCommand::LookupDidDht(did, tx) => {
                        let query_id = swarm.behaviour_mut().kademlia.get_record(libp2p::kad::RecordKey::new(&did));
                        pending_did_queries.insert(query_id, tx);
                        eprintln!("Looking up DID {} in Kademlia DHT", did);
                    }
                    SwarmCommand::PublishDht(name, res) => {
                        let record = libp2p::kad::Record {
                            key: libp2p::kad::RecordKey::new(&name),
                            value: serde_json::to_vec(&res).unwrap(),
                            publisher: None,
                            expires: None,
                        };
                        let _ = swarm.behaviour_mut().kademlia.put_record(record, libp2p::kad::Quorum::One);
                        eprintln!("Published {} to Kademlia DHT", name);
                    }
                    SwarmCommand::LookupDht(name, tx) => {
                        let query_id = swarm.behaviour_mut().kademlia.get_record(libp2p::kad::RecordKey::new(&name));
                        pending_queries.insert(query_id, tx);
                        eprintln!("Looking up {} in Kademlia DHT", name);
                    }
                    SwarmCommand::PublishReputationDht(wallet, reputation) => {
                        let rep_record = ReputationRecord {
                            reputation,
                            updated_at: std::time::SystemTime::now()
                                .duration_since(std::time::UNIX_EPOCH)
                                .unwrap()
                                .as_secs(),
                        };
                        let rep_key = format!("/reputation/{}", wallet);
                        if let Ok(value) = serde_json::to_vec(&rep_record) {
                            let record = libp2p::kad::Record {
                                key: libp2p::kad::RecordKey::new(&rep_key),
                                value,
                                publisher: None,
                                expires: None,
                            };
                            let _ = swarm.behaviour_mut().kademlia.put_record(record, libp2p::kad::Quorum::One);
                            eprintln!("[REPUTATION] Published reputation {}={} to DHT", wallet, reputation);
                        }
                    }
                }
            }
        }
    }
}