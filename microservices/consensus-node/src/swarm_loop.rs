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
    PublishName(String, String, String), // name, did, public_key
    PublishDidUpdate(String, String), // dummy for future use
    PublishDht(String, crate::ResolveRes), // name, resolve_res
    LookupDht(String, tokio::sync::oneshot::Sender<Option<crate::ResolveRes>>), // name, callback
}

#[derive(serde::Serialize, serde::Deserialize)]
pub struct NameRegistrationPayload {
    pub name: String,
    pub did: String,
    pub public_key: String,
}

pub async fn run_swarm(
    mut swarm: Swarm<ConsensusBehaviour>,
    mut command_rx: mpsc::UnboundedReceiver<SwarmCommand>,
    ppor_manager: Arc<Mutex<crate::ppor::PporManager>>,
    name_db: Arc<Mutex<crate::name_db::NameDb>>,
) {
    use std::collections::HashMap;
    let mut pending_queries: HashMap<libp2p::kad::QueryId, tokio::sync::oneshot::Sender<Option<crate::ResolveRes>>> = HashMap::new();

    loop {
        tokio::select! {
            event = swarm.select_next_some() => {
                match event {
                    SwarmEvent::NewListenAddr { address, .. } => {
                        println!("Consensus node listening on P2P address: {}", address);
                    }
                    SwarmEvent::ConnectionEstablished { peer_id, .. } => {
                        println!("Consensus connected to {}", peer_id);
                    }
                    SwarmEvent::Behaviour(ConsensusBehaviourEvent::Gossipsub(libp2p::gossipsub::Event::Message { message, .. })) => {
                        let topic = message.topic.as_str();
                        if topic == "feedo_consensus_ppor" {
                            if let Ok(pbft_msg) = prost::Message::decode(&message.data[..]) {
                                let mut manager = ppor_manager.lock().await;
                                if let Some(reply_msg) = manager.handle_message(pbft_msg) {
                                    let data = prost::Message::encode_to_vec(&reply_msg);
                                    let topic = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                    let _ = swarm.behaviour_mut().gossipsub.publish(topic, data);
                                }
                            }
                        } else if topic == "feedo_name_registrations" {
                            if let Ok(reg) = serde_json::from_slice::<NameRegistrationPayload>(&message.data) {
                                let db = name_db.lock().await;
                                let _ = db.insert_name(&reg.name, &reg.did, &reg.public_key);
                                println!("Decentralized Name registered: {}", reg.name);
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
                    SwarmCommand::PublishName(name, did, public_key) => {
                        let payload = NameRegistrationPayload { name, did, public_key };
                        if let Ok(data) = serde_json::to_vec(&payload) {
                            let topic = libp2p::gossipsub::IdentTopic::new("feedo_name_registrations");
                            if let Err(e) = swarm.behaviour_mut().gossipsub.publish(topic, data) {
                                println!("Failed to publish name registration: {:?}", e);
                            }
                        }
                    }
                    SwarmCommand::PublishDidUpdate(_, _) => {
                        // For future
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
