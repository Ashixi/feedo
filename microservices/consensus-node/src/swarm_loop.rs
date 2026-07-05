use crate::network::{ConsensusBehaviour, ConsensusBehaviourEvent};
use libp2p::swarm::SwarmEvent;
use libp2p::Swarm;
use tokio::sync::mpsc;
use futures::StreamExt;
use std::sync::Arc;
use tokio::sync::Mutex;
use shared_proto::feedo::PbftMessage;

pub enum SwarmCommand {
    PublishPbft(PbftMessage),
    PublishName(String, String, String), // name, did, public_key
    PublishDidUpdate(String, String), // dummy for future use
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
    pbft_manager: Arc<Mutex<crate::pbft::PbftManager>>,
    name_db: Arc<Mutex<crate::name_db::NameDb>>,
) {
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
                        if topic == "feedo_consensus_pbft" {
                            if let Ok(pbft_msg) = prost::Message::decode(&message.data[..]) {
                                let mut manager = pbft_manager.lock().await;
                                if let Some(reply_msg) = manager.handle_message(pbft_msg, 4) { // total nodes = 4 for example
                                    let data = prost::Message::encode_to_vec(&reply_msg);
                                    let topic = libp2p::gossipsub::IdentTopic::new("feedo_consensus_pbft");
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
                    SwarmEvent::Behaviour(ConsensusBehaviourEvent::Kademlia(libp2p::kad::Event::RoutingUpdated { peer, is_new_peer, .. })) => {
                        if is_new_peer {
                            println!("Consensus Kademlia DHT discovered a new node: {}", peer);
                        }
                    }
                    _ => {}
                }
            }
            Some(command) = command_rx.recv() => {
                match command {
                    SwarmCommand::PublishPbft(msg) => {
                        let data = prost::Message::encode_to_vec(&msg);
                        let topic = libp2p::gossipsub::IdentTopic::new("feedo_consensus_pbft");
                        if let Err(e) = swarm.behaviour_mut().gossipsub.publish(topic, data) {
                            println!("Failed to publish PBFT message: {:?}", e);
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
                }
            }
        }
    }
}
