use crate::network::{ConsensusBehaviour, ConsensusBehaviourEvent};
use libp2p::swarm::SwarmEvent;
use libp2p::Swarm;
use tokio::sync::mpsc;
use futures::StreamExt;
use std::sync::Arc;
use tokio::sync::Mutex;
use shared_proto::feedo::PbftMessage;

pub enum SwarmCommand {
    PublishPpor(PbftMessage),
    BroadcastNameTx(crate::NameRegistrationTx),
    BroadcastUpdateCidTx(crate::UpdateCidTx),
    BroadcastLedgerTx(crate::LedgerTx),
    PublishDidDht(String, crate::did::DidDocument),
    PublishDht(String, crate::ResolveRes), // name, resolve_res
    LookupDht(String, tokio::sync::oneshot::Sender<Option<crate::ResolveRes>>), // name, callback
    LookupDidDht(String, tokio::sync::oneshot::Sender<Option<crate::did::DidDocument>>),
}

pub async fn run_swarm(
    mut swarm: Swarm<ConsensusBehaviour>,
    mut command_rx: mpsc::UnboundedReceiver<SwarmCommand>,
    ppor_manager: Arc<Mutex<crate::ppor::PporManager>>,
    name_db: Arc<Mutex<crate::name_db::NameDb>>,
    _did_manager: Arc<Mutex<crate::did::DidManager>>,
    ledger: Arc<crate::accounting::Ledger>,
) {
    use std::collections::HashMap;
    let mut pending_queries: HashMap<libp2p::kad::QueryId, tokio::sync::oneshot::Sender<Option<crate::ResolveRes>>> = HashMap::new();
    let mut pending_name_txs: HashMap<String, crate::NameRegistrationTx> = HashMap::new();
    let mut pending_cid_txs: HashMap<String, crate::UpdateCidTx> = HashMap::new();
    let mut pending_ledger_txs: HashMap<String, crate::LedgerTx> = HashMap::new();

    loop {
        tokio::select! {
            event = swarm.select_next_some() => {
                match event {
                    SwarmEvent::NewListenAddr { address, .. } => {
                        println!("Consensus node listening on P2P address: {}", address);
                    }
                    SwarmEvent::ConnectionEstablished { peer_id, .. } => {
                        println!("Consensus connected to {}", peer_id);
                        // Peer з'єднано. Комітет формується виключно зі смартконтракту.
                    }
                    SwarmEvent::Behaviour(ConsensusBehaviourEvent::Gossipsub(libp2p::gossipsub::Event::Message { message, .. })) => {
                        let topic = message.topic.as_str();
                        if topic == "feedo_consensus_ppor" {
                            if let Ok(pbft_msg) = <shared_proto::feedo::PbftMessage as prost::Message>::decode(&message.data[..]) {
                                let mut manager = ppor_manager.lock().await;
                                if let Some(reply_msg) = manager.handle_message(pbft_msg.clone()) {
                                    let data = prost::Message::encode_to_vec(&reply_msg);
                                    let topic = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                    let _ = swarm.behaviour_mut().gossipsub.publish(topic, data);
                                }
                                // Check if this message finalized a transaction
                                if pbft_msg.phase == shared_proto::feedo::PbftPhase::Finalized as i32 {
                                    if pbft_msg.tx_type == crate::ppor::TX_TYPE_NAME_REGISTRATION {
                                        if let Some(tx) = pending_name_txs.remove(&pbft_msg.tx_hash) {
                                            // Deduct credits from ledger
                                            if ledger.debit(&tx.did, 100).await {
                                                let db = name_db.lock().await;
                                                let _ = db.insert_name(&tx.name, &tx.did, &tx.public_key);
                                                println!("Decentralized Name FINALIZED: {}", tx.name);
                                                
                                                // DHT publish
                                                let res = crate::ResolveRes { did: tx.did, cid: None, gateways: None };
                                                let record = libp2p::kad::Record {
                                                    key: libp2p::kad::RecordKey::new(&tx.name),
                                                    value: serde_json::to_vec(&res).unwrap(),
                                                    publisher: None,
                                                    expires: None,
                                                };
                                                let _ = swarm.behaviour_mut().kademlia.put_record(record, libp2p::kad::Quorum::One);
                                            }
                                        }
                                    } else if pbft_msg.tx_type == crate::ppor::TX_TYPE_UPDATE_CID {
                                        if let Some(tx) = pending_cid_txs.remove(&pbft_msg.tx_hash) {
                                            let db = name_db.lock().await;
                                            if let Ok(Some((did, _, _))) = db.resolve_name(&tx.name) {
                                                let gateways_json = serde_json::to_string(&tx.gateways).unwrap_or_else(|_| "[]".to_string());
                                                let _ = db.update_cid(&tx.name, &tx.cid, &gateways_json);
                                                println!("Decentralized CID UPDATE FINALIZED: {} -> {}", tx.name, tx.cid);
                                                
                                                // DHT publish
                                                let res = crate::ResolveRes { did, cid: Some(tx.cid), gateways: Some(tx.gateways) };
                                                let record = libp2p::kad::Record {
                                                    key: libp2p::kad::RecordKey::new(&tx.name),
                                                    value: serde_json::to_vec(&res).unwrap(),
                                                    publisher: None,
                                                    expires: None,
                                                };
                                                let _ = swarm.behaviour_mut().kademlia.put_record(record, libp2p::kad::Quorum::One);
                                            }
                                        }
                                    } else if pbft_msg.tx_type == crate::ppor::TX_TYPE_LEDGER {
                                        if let Some(tx) = pending_ledger_txs.remove(&pbft_msg.tx_hash) {
                                            if tx.is_credit {
                                                ledger.credit(&tx.did, tx.amount).await;
                                                println!("Decentralized Ledger CREDIT FINALIZED: {} for {}", tx.amount, tx.did);
                                            } else {
                                                let _ = ledger.debit(&tx.did, tx.amount).await;
                                                println!("Decentralized Ledger DEBIT FINALIZED: {} from {}", tx.amount, tx.did);
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
                                    if let Some(reply_msg) = manager.mark_validated(&hash, crate::ppor::TX_TYPE_NAME_REGISTRATION) {
                                        let data = prost::Message::encode_to_vec(&reply_msg);
                                        let topic = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                        let _ = swarm.behaviour_mut().gossipsub.publish(topic, data);
                                    }
                                }
                            }
                        } else if topic == "feedo_update_cid_txs" {
                            if let Ok(tx) = serde_json::from_slice::<crate::UpdateCidTx>(&message.data) {
                                let hash = tx.tx_hash();
                                pending_cid_txs.insert(hash.clone(), tx);
                                
                                let mut manager = ppor_manager.lock().await;
                                if let Some(reply_msg) = manager.mark_validated(&hash, crate::ppor::TX_TYPE_UPDATE_CID) {
                                    let data = prost::Message::encode_to_vec(&reply_msg);
                                    let topic = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                    let _ = swarm.behaviour_mut().gossipsub.publish(topic, data);
                                }
                            }
                        } else if topic == "feedo_ledger_txs" {
                            if let Ok(tx) = serde_json::from_slice::<crate::LedgerTx>(&message.data) {
                                // Assume signature is valid if SYSTEM, or otherwise validated.
                                // Real implementation would check the signature here.
                                let hash = tx.tx_hash();
                                pending_ledger_txs.insert(hash.clone(), tx);
                                
                                let mut manager = ppor_manager.lock().await;
                                if let Some(reply_msg) = manager.mark_validated(&hash, crate::ppor::TX_TYPE_LEDGER) {
                                    let data = prost::Message::encode_to_vec(&reply_msg);
                                    let topic = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                    let _ = swarm.behaviour_mut().gossipsub.publish(topic, data);
                                }
                            }
                        }
                    }
                    SwarmEvent::Behaviour(ConsensusBehaviourEvent::Kademlia(event)) => {
                        match event {
                            libp2p::kad::Event::RoutingUpdated { peer, is_new_peer, .. } => {
                                if is_new_peer {
                                    println!("Consensus Kademlia DHT discovered a new node: {}", peer);
                                }
                            }
                            libp2p::kad::Event::OutboundQueryProgressed { id, result, .. } => {
                                if let Some(tx) = pending_queries.remove(&id) {
                                    match result {
                                        libp2p::kad::QueryResult::GetRecord(Ok(libp2p::kad::GetRecordOk::FoundRecord(peer_record))) => {
                                            if let Ok(res) = serde_json::from_slice::<crate::ResolveRes>(&peer_record.record.value) {
                                                let _ = tx.send(Some(res));
                                                continue;
                                            }
                                            let _ = tx.send(None);
                                        }
                                        _ => {
                                            let _ = tx.send(None);
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
                    SwarmCommand::PublishPpor(msg) => {
                        let data = prost::Message::encode_to_vec(&msg);
                        let topic = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                        if let Err(e) = swarm.behaviour_mut().gossipsub.publish(topic, data) {
                            println!("Failed to publish PPoR message: {:?}", e);
                        }
                    }
                    SwarmCommand::BroadcastNameTx(tx) => {
                        if let Ok(data) = serde_json::to_vec(&tx) {
                            let topic = libp2p::gossipsub::IdentTopic::new("feedo_name_txs");
                            if let Err(e) = swarm.behaviour_mut().gossipsub.publish(topic, data) {
                                println!("Failed to publish NameRegistrationTx: {:?}", e);
                            }
                        }
                    }
                    SwarmCommand::BroadcastUpdateCidTx(tx) => {
                        if let Ok(data) = serde_json::to_vec(&tx) {
                            let topic = libp2p::gossipsub::IdentTopic::new("feedo_update_cid_txs");
                            if let Err(e) = swarm.behaviour_mut().gossipsub.publish(topic, data) {
                                println!("Failed to publish UpdateCidTx: {:?}", e);
                            }
                        }
                    }
                    SwarmCommand::BroadcastLedgerTx(tx) => {
                        if let Ok(data) = serde_json::to_vec(&tx) {
                            let topic = libp2p::gossipsub::IdentTopic::new("feedo_ledger_txs");
                            if let Err(e) = swarm.behaviour_mut().gossipsub.publish(topic, data) {
                                println!("Failed to publish LedgerTx: {:?}", e);
                            }
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
                        println!("Published DID {} to Kademlia DHT", did);
                    }
                    SwarmCommand::LookupDidDht(_, _) => {
                        // Removed
                    }
                    SwarmCommand::PublishDht(name, res) => {
                        let record = libp2p::kad::Record {
                            key: libp2p::kad::RecordKey::new(&name),
                            value: serde_json::to_vec(&res).unwrap(),
                            publisher: None,
                            expires: None,
                        };
                        let _ = swarm.behaviour_mut().kademlia.put_record(record, libp2p::kad::Quorum::One);
                        println!("Published {} to Kademlia DHT", name);
                    }
                    SwarmCommand::LookupDht(name, tx) => {
                        let query_id = swarm.behaviour_mut().kademlia.get_record(libp2p::kad::RecordKey::new(&name));
                        pending_queries.insert(query_id, tx);
                        println!("Looking up {} in Kademlia DHT", name);
                    }
                }
            }
        }
    }
}
