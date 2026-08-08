use crate::network::{
    ConsensusBehaviour, ConsensusBehaviourEvent, ConsensusRequest, ConsensusResponse,
};
use libp2p::swarm::SwarmEvent;
use libp2p::Swarm;
use tokio::sync::mpsc;
use futures::StreamExt;
use std::sync::Arc;
use tokio::sync::Mutex;
use shared_proto::feedo::{PbftMessage, PbftPhase};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::time::Duration;
use base64::{Engine as _, engine::general_purpose::STANDARD as BASE64};

/// Announcement message published on "feedo_peer_announce" gossipsub topic.
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct PeerAnnounce {
    pub peer_id: String,
    pub wallet_address: String,
    pub reputation: u64,
    pub version: String,
    pub api_url: Option<String>,
    pub grpc_url: Option<String>,
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
    BroadcastUpdateMetadataTx(crate::UpdateMetadataTx),
    PublishDidDht(String, crate::did::DidDocument),
    PublishDht(String, crate::ResolveRes),
    LookupDht(
        String,
        tokio::sync::oneshot::Sender<Option<crate::ResolveRes>>,
    ),
    LookupDidDht(
        String,
        tokio::sync::oneshot::Sender<Option<crate::did::DidDocument>>,
    ),
    PublishReputationDht(String, u64), // wallet_address, reputation_score
    PublishAclDht(String, String, String), // file_hash, grantee_did, encrypted_key
    QueryAclDht(String, String, tokio::sync::oneshot::Sender<Option<String>>), // file_hash, grantee_did, response_tx

    // Grant system
    CreateGrant {
        grant: crate::ppor::GrantProgram,
        response_tx: tokio::sync::oneshot::Sender<Result<(), String>>,
    },
    ClaimGrant {
        grant_id: String,
        did: String,
        response_tx: tokio::sync::oneshot::Sender<Result<(u64, u64), String>>,
    },
    GetGrantInfo {
        grant_id: String,
        response_tx: tokio::sync::oneshot::Sender<Option<GrantInfoResponse>>,
    },
    ListGrants {
        response_tx: tokio::sync::oneshot::Sender<Vec<GrantInfoResponse>>,
    },
}

/// Response structure for grant info queries (exposed via HTTP API).
#[derive(Debug, Clone, Serialize)]
pub struct GrantInfoResponse {
    pub grant_id: String,
    pub title: String,
    pub verification: String,
    pub amount_per_claim: u64,
    pub max_claims: u64,
    pub claimed_count: u64,
    pub claimed_total: u64,
    pub active: bool,
    pub expires_at: u64,
    pub created_at: u64,
}

// ============================================================================
// Phase 1 Helper Functions — Direct PBFT message routing
// ============================================================================

/// Returns PeerIds of current committee members (excluding self) that we have a mapping for.
fn get_committee_peers(
    committee: &HashSet<String>,
    my_wallet: &str,
    wallet_to_peer: &HashMap<String, libp2p::PeerId>,
) -> Vec<libp2p::PeerId> {
    committee
        .iter()
        .filter(|w| *w != my_wallet)
        .filter_map(|w| wallet_to_peer.get(w).copied())
        .collect()
}

/// Sends a PBFT message to all committee members (except self) via direct request-response.
/// Falls back to gossipsub if no peers are available (e.g., self-only committee).
/// Returns true if the message was delivered via direct request-response.
fn send_pbft_to_committee(
    swarm: &mut Swarm<ConsensusBehaviour>,
    msg: &PbftMessage,
    committee: &HashSet<String>,
    my_wallet: &str,
    wallet_to_peer: &HashMap<String, libp2p::PeerId>,
) -> bool {
    let peers = get_committee_peers(committee, my_wallet, wallet_to_peer);
    if peers.is_empty() {
        // Fallback: no other committee peers known — publish via gossipsub
        // for backward compatibility (self-only committee, transition period).
        let data = prost::Message::encode_to_vec(msg);
        let topic = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
        let _ = swarm.behaviour_mut().gossipsub.publish(topic, data);
        eprintln!(
            "[PBFT_FALLBACK] No committee peers known — published {:?} via gossipsub for tx={}",
            PbftPhase::try_from(msg.phase).ok(),
            &msg.tx_hash[..16.min(msg.tx_hash.len())]
        );
        return false;
    }

    let pbft_b64 = BASE64.encode(prost::Message::encode_to_vec(msg));
    let request = ConsensusRequest::PbftVote {
        pbft_message_b64: pbft_b64,
        phase: msg.phase,
        tx_hash: msg.tx_hash.clone(),
    };
    let mut sent = 0usize;
    for peer_id in &peers {
        let _request_id = swarm
            .behaviour_mut()
            .request_response
            .send_request(peer_id, request.clone());
        sent += 1;
    }
    eprintln!(
        "[PBFT_DIRECT] Sent {:?} to {} peers for tx={}",
        PbftPhase::try_from(msg.phase).ok(),
        sent,
        &msg.tx_hash[..16.min(msg.tx_hash.len())]
    );
    true
}

/// Handles a finalized transaction: applies it to storage, publishes to DHT, cleans up state.
/// Extracted to avoid code duplication across the 5 gossipsub handlers.
async fn handle_finalized_tx(
    pbft_msg: &PbftMessage,
    manager: &mut crate::ppor::PporManager,
    name_db: &Arc<Mutex<crate::name_db::NameDb>>,
    ledger: &Arc<crate::accounting::Ledger>,
    pending_name_txs: &mut HashMap<String, crate::NameRegistrationTx>,
    pending_cid_txs: &mut HashMap<String, crate::UpdateCidTx>,
    pending_ledger_txs: &mut HashMap<String, crate::LedgerTx>,
    pending_metadata_txs: &mut HashMap<String, crate::UpdateMetadataTx>,
    swarm: &mut Swarm<ConsensusBehaviour>,
) {
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
                    title: None,
                    description: None,
                    icon_cid: None,
                    created_at: Some(finalized_at as i64),
                    updated_at: None,
                };
                let record = libp2p::kad::Record {
                    key: libp2p::kad::RecordKey::new(&tx.name),
                    value: serde_json::to_vec(&res).unwrap(),
                    publisher: None,
                    expires: None,
                };
                let _ =
                    swarm
                        .behaviour_mut()
                        .kademlia
                        .put_record(record, libp2p::kad::Quorum::One);
                manager.states.remove(&pbft_msg.tx_hash);
            }
        }
    } else if pbft_msg.tx_type == crate::ppor::TX_TYPE_UPDATE_CID {
        if let Some(tx) = pending_cid_txs.remove(&pbft_msg.tx_hash) {
            let db = name_db.lock().await;
            if let Ok(Some((did, _, _))) = db.resolve_name(&tx.name) {
                let gateways_json =
                    serde_json::to_string(&tx.gateways).unwrap_or_else(|_| "[]".to_string());
                let _ = db.update_cid(&tx.name, &tx.cid, &gateways_json);
                eprintln!(
                    "Decentralized CID UPDATE FINALIZED: {} -> {}",
                    tx.name, tx.cid
                );
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
                    title: None,
                    description: None,
                    icon_cid: None,
                    created_at: None,
                    updated_at: Some(finalized_at as i64),
                };
                let record = libp2p::kad::Record {
                    key: libp2p::kad::RecordKey::new(&tx.name),
                    value: serde_json::to_vec(&res).unwrap(),
                    publisher: None,
                    expires: None,
                };
                let _ =
                    swarm
                        .behaviour_mut()
                        .kademlia
                        .put_record(record, libp2p::kad::Quorum::One);
                // Phase 1.5: archive finalized state instead of raw remove
                manager.archive_finalized_state(&pbft_msg.tx_hash);
            }
        }
    } else if pbft_msg.tx_type == crate::ppor::TX_TYPE_LEDGER {
        if let Some(tx) = pending_ledger_txs.remove(&pbft_msg.tx_hash) {
            if tx.is_credit {
                ledger.credit(&tx.did, tx.amount).await;
                eprintln!(
                    "Decentralized Ledger CREDIT FINALIZED: {} for {}",
                    tx.amount, tx.did
                );
            } else {
                let _ = ledger.debit(&tx.did, tx.amount).await;
                eprintln!(
                    "Decentralized Ledger DEBIT FINALIZED: {} from {}",
                    tx.amount, tx.did
                );
            }
        }
    } else if pbft_msg.tx_type == crate::ppor::TX_TYPE_UPDATE_METADATA {
        if let Some(tx) = pending_metadata_txs.remove(&pbft_msg.tx_hash) {
            let db = name_db.lock().await;
            let _ = db.update_metadata(&tx.name, &tx.title, &tx.description, &tx.icon_cid);
            eprintln!("Decentralized Metadata UPDATE FINALIZED: {}", tx.name);
            let finalized_at = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs();
            let epoch = manager.current_epoch;
            let res = crate::ResolveRes {
                did: String::new(),
                cid: None,
                gateways: None,
                epoch: Some(epoch),
                finalized_at: Some(finalized_at),
                title: tx.title,
                description: tx.description,
                icon_cid: tx.icon_cid,
                created_at: None,
                updated_at: Some(finalized_at as i64),
            };
            let record = libp2p::kad::Record {
                key: libp2p::kad::RecordKey::new(&tx.name),
                value: serde_json::to_vec(&res).unwrap(),
                publisher: None,
                expires: None,
            };
            let _ = swarm
                .behaviour_mut()
                .kademlia
                .put_record(record, libp2p::kad::Quorum::One);
            // Phase 1.5: archive finalized state instead of raw remove
            manager.archive_finalized_state(&pbft_msg.tx_hash);
        }
    }
}

/// Self-deliver PBFT message chain: call handle_message() locally up to 3 times
/// to progress through Prepare → Commit → Finalized, sending each phase to the committee.
fn self_deliver_pbft_chain(
    manager: &mut crate::ppor::PporManager,
    initial_msg: Option<PbftMessage>,
    swarm: &mut Swarm<ConsensusBehaviour>,
    committee: &HashSet<String>,
    my_wallet: &str,
    wallet_to_peer: &HashMap<String, libp2p::PeerId>,
) -> Option<PbftMessage> {
    let mut current = initial_msg;
    // Chain up to 3 self-deliver rounds (PrePrepare→Prepare→Commit→Finalized)
    for _round in 0..3 {
        let next = current.and_then(|m| manager.handle_message(m));
        if let Some(ref reply) = next {
            send_pbft_to_committee(swarm, reply, committee, my_wallet, wallet_to_peer);
        }
        current = next;
    }
    // Return the final message (could be Finalized)
    current
}

pub async fn run_swarm(
    mut swarm: Swarm<ConsensusBehaviour>,
    mut command_rx: mpsc::UnboundedReceiver<SwarmCommand>,
    ppor_manager: Arc<Mutex<crate::ppor::PporManager>>,
    name_db: Arc<Mutex<crate::name_db::NameDb>>,
    _did_manager: Arc<Mutex<crate::did::DidManager>>,
    ledger: Arc<crate::accounting::Ledger>,
    telemetry_cache: Arc<Mutex<crate::telemetry::TelemetryCache>>,
) {
    // Check if direct consensus mode is enabled (Phase 1).
    // When true, PBFT messages go via direct request-response instead of gossipsub.
    // Gossipsub listener for feedo_consensus_ppor is kept for backward-compat.
    let direct_mode = std::env::var("CONSENSUS_DIRECT_MODE")
        .unwrap_or_else(|_| "true".to_string())
        == "true";
    if direct_mode {
        eprintln!(
            "[CONSENSUS] Direct request-response mode ENABLED (Phase 1) — PBFT goes direct, not via gossipsub"
        );
    } else {
        eprintln!(
            "[CONSENSUS] Direct mode DISABLED — using gossipsub for PBFT (backward-compat)"
        );
    }

    let mut pending_queries: HashMap<
        libp2p::kad::QueryId,
        tokio::sync::oneshot::Sender<Option<crate::ResolveRes>>,
    > = HashMap::new();
    let mut pending_did_queries: HashMap<
        libp2p::kad::QueryId,
        tokio::sync::oneshot::Sender<Option<crate::did::DidDocument>>,
    > = HashMap::new();
    let mut pending_acl_queries: HashMap<
        libp2p::kad::QueryId,
        tokio::sync::oneshot::Sender<Option<String>>,
    > = HashMap::new();
    let mut pending_name_txs: HashMap<String, crate::NameRegistrationTx> = HashMap::new();
    let mut pending_cid_txs: HashMap<String, crate::UpdateCidTx> = HashMap::new();
    let mut pending_ledger_txs: HashMap<String, crate::LedgerTx> = HashMap::new();
    let mut pending_metadata_txs: HashMap<String, crate::UpdateMetadataTx> = HashMap::new();
    // Maps wallet_address -> PeerId (populated via peer_announce + identify)
    let mut wallet_to_peer: HashMap<String, libp2p::PeerId> = HashMap::new();
    // Maps PeerId -> wallet_address (for reverse lookup)
    let mut peer_to_wallet: HashMap<libp2p::PeerId, String> = HashMap::new();

    let mut peer_cache = crate::peer_cache::PeerCache::load("peer_cache.json");

    let http_port: u16 = std::env::var("HTTP_PORT").unwrap_or_else(|_| "3000".to_string()).parse().unwrap_or(3000);
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
    let grpc_port: u16 = std::env::var("GRPC_PORT").unwrap_or_else(|_| "50051".to_string()).parse().unwrap_or(50051);
    let grpc_url = format!("{}:{}", public_ip, grpc_port);

    // --- Publish our own announcement on startup ---
    {
        let manager = ppor_manager.lock().await;
        let my_peer_id = swarm.local_peer_id().to_string();
        let my_wallet = manager.node_id.clone();
        let my_reputation = manager
            .reputation_table
            .get(&my_wallet)
            .copied()
            .unwrap_or(10);
        drop(manager);
        let announce = PeerAnnounce {
            peer_id: my_peer_id.clone(),
            wallet_address: my_wallet.clone(),
            reputation: my_reputation,
            version: "1.0.0".to_string(),
            api_url: Some(http_url.clone()),
            grpc_url: Some(grpc_url.clone()),
        };
        eprintln!(
            "[BOOTSTRAP] Published self-announce: wallet={}, peer={}",
            my_wallet, my_peer_id
        );
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
            let _ = swarm
                .behaviour_mut()
                .kademlia
                .put_record(record, libp2p::kad::Quorum::One);
        }
    }

    // Proactive epoch tick — checks epoch rotation every 5 seconds independently
    // of PBFT traffic. This ensures epoch progresses even when there are no transactions.
    let mut epoch_tick = tokio::time::interval(Duration::from_secs(5));
    let mut announce_tick = tokio::time::interval(Duration::from_secs(60));
    let mut telemetry_tick = tokio::time::interval(Duration::from_secs(300));

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
                    SwarmEvent::Behaviour(ConsensusBehaviourEvent::Identify(
                        libp2p::identify::Event::Received { peer_id, info, .. }
                    )) => {
                        eprintln!(
                            "[IDENTIFY] Received from {}: protocol={}",
                            peer_id, info.protocol_version
                        );
                    }

                    // ================================================================
                    // Phase 1: Unified RequestResponse handler for TxRelay + PbftVote
                    // ================================================================
                    SwarmEvent::Behaviour(ConsensusBehaviourEvent::RequestResponse(
                        libp2p::request_response::Event::Message { peer: _, message }
                    )) => {
                        match message {
                            libp2p::request_response::Message::Request {
                                request_id: _,
                                request,
                                channel,
                            } => match request {
                                // --- TxRelay: initial transaction relay from another node ---
                                ConsensusRequest::TxRelay {
                                    tx_type,
                                    tx_data_json,
                                    from_node,
                                    signature: _sig,
                                } => {
                                    eprintln!(
                                        "[TX_RELAY] Received transaction from {}: type={}",
                                        from_node, tx_type
                                    );
                                    let tx_hash = {
                                        use sha2::{Sha256, Digest};
                                        let mut hasher = Sha256::new();
                                        hasher.update(format!(
                                            "{}{}{}",
                                            tx_type, tx_data_json, from_node
                                        ));
                                        hex::encode(hasher.finalize())
                                    };

                                    let mut manager = ppor_manager.lock().await;
                                    let tx_type_i32: i32 = tx_type.parse().unwrap_or(0);
                                    let reply_msg =
                                        manager.propose(tx_hash.clone(), 0, tx_type_i32);
                                    let committee = manager.current_committee.clone();
                                    let my_wallet = manager.node_id.clone();

                                    if let Some(ref proose_msg) = reply_msg {
                                        if direct_mode {
                                            // Phase 1: send direct, not via gossipsub
                                            send_pbft_to_committee(
                                                &mut swarm,
                                                proose_msg,
                                                &committee,
                                                &my_wallet,
                                                &wallet_to_peer,
                                            );
                                            // Self-deliver chain
                                            let final_msg = self_deliver_pbft_chain(
                                                &mut manager,
                                                Some(proose_msg.clone()),
                                                &mut swarm,
                                                &committee,
                                                &my_wallet,
                                                &wallet_to_peer,
                                            );
                                            // Check if finalized
                                            if let Some(ref fmsg) = final_msg {
                                                if fmsg.phase == PbftPhase::Finalized as i32 {
                                                    handle_finalized_tx(
                                                        fmsg,
                                                        &mut manager,
                                                        &name_db,
                                                        &ledger,
                                                        &mut pending_name_txs,
                                                        &mut pending_cid_txs,
                                                        &mut pending_ledger_txs,
                                                        &mut pending_metadata_txs,
                                                        &mut swarm,
                                                    )
                                                    .await;
                                                }
                                            }
                                        } else {
                                            // Backward-compat: publish via gossipsub
                                            let data = prost::Message::encode_to_vec(proose_msg);
                                            let topic = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                                            let _ = swarm.behaviour_mut().gossipsub.publish(topic, data);
                                        }
                                    }

                                    // Store pending tx for later finalized handling
                                    if let Ok(tx_data) =
                                        serde_json::from_str::<serde_json::Value>(&tx_data_json)
                                    {
                                        if tx_type_i32 == crate::ppor::TX_TYPE_NAME_REGISTRATION {
                                            if let Ok(tx) =
                                                serde_json::from_value::<crate::NameRegistrationTx>(tx_data)
                                            {
                                                pending_name_txs.insert(tx_hash.clone(), tx);
                                            }
                                        } else if tx_type_i32 == crate::ppor::TX_TYPE_UPDATE_CID {
                                            if let Ok(tx) =
                                                serde_json::from_value::<crate::UpdateCidTx>(tx_data)
                                            {
                                                pending_cid_txs.insert(tx_hash.clone(), tx);
                                            }
                                        } else if tx_type_i32 == crate::ppor::TX_TYPE_LEDGER {
                                            if let Ok(tx) =
                                                serde_json::from_value::<crate::LedgerTx>(tx_data)
                                            {
                                                pending_ledger_txs.insert(tx_hash.clone(), tx);
                                            }
                                        } else if tx_type_i32 == crate::ppor::TX_TYPE_UPDATE_METADATA {
                                            if let Ok(tx) =
                                                serde_json::from_value::<crate::UpdateMetadataTx>(tx_data)
                                            {
                                                pending_metadata_txs.insert(tx_hash.clone(), tx);
                                            }
                                        }
                                    }
                                    drop(manager);

                                    let response = ConsensusResponse::TxAck {
                                        accepted: true,
                                        reason: "ok".to_string(),
                                    };
                                    let _ = swarm
                                        .behaviour_mut()
                                        .request_response
                                        .send_response(channel, response);
                                }

                                // --- PbftVote: direct PBFT phase message from another validator ---
                                ConsensusRequest::PbftVote {
                                    pbft_message_b64,
                                    phase: _,
                                    tx_hash: _,
                                } => {
                                    let msg_bytes = match BASE64.decode(&pbft_message_b64) {
                                        Ok(b) => b,
                                        Err(e) => {
                                            eprintln!("[PBFT_DIRECT] Failed to decode base64 PbftMessage: {}", e);
                                            let _ = swarm.behaviour_mut().request_response.send_response(
                                                channel,
                                                ConsensusResponse::PbftAck { received: false },
                                            );
                                            continue;
                                        }
                                    };
                                    let pbft_msg = match <PbftMessage as prost::Message>::decode(&msg_bytes[..]) {
                                        Ok(m) => m,
                                        Err(e) => {
                                            eprintln!("[PBFT_DIRECT] Failed to decode protobuf PbftMessage: {}", e);
                                            let _ = swarm.behaviour_mut().request_response.send_response(
                                                channel,
                                                ConsensusResponse::PbftAck { received: false },
                                            );
                                            continue;
                                        }
                                    };

                                    eprintln!(
                                        "[PBFT_DIRECT] Received {:?} for tx={}",
                                        PbftPhase::try_from(pbft_msg.phase).ok(),
                                        &pbft_msg.tx_hash[..16.min(pbft_msg.tx_hash.len())]
                                    );

                                    let mut manager = ppor_manager.lock().await;
                                    let committee = manager.current_committee.clone();
                                    let my_wallet = manager.node_id.clone();

                                    // Process the incoming message
                                    let final_msg = self_deliver_pbft_chain(
                                        &mut manager,
                                        Some(pbft_msg),
                                        &mut swarm,
                                        &committee,
                                        &my_wallet,
                                        &wallet_to_peer,
                                    );

                                    // Handle finalized
                                    if let Some(ref fmsg) = final_msg {
                                        if fmsg.phase == PbftPhase::Finalized as i32 {
                                            handle_finalized_tx(
                                                fmsg,
                                                &mut manager,
                                                &name_db,
                                                &ledger,
                                                &mut pending_name_txs,
                                                &mut pending_cid_txs,
                                                &mut pending_ledger_txs,
                                                &mut pending_metadata_txs,
                                                &mut swarm,
                                            )
                                            .await;
                                        }
                                    }
                                    drop(manager);

                                    let _ = swarm
                                        .behaviour_mut()
                                        .request_response
                                        .send_response(
                                            channel,
                                            ConsensusResponse::PbftAck { received: true },
                                        );
                                }
                                ConsensusRequest::PeerAnnounce { announce_json } => {
                                    if let Ok(announce) = serde_json::from_str::<PeerAnnounce>(&announce_json) {
                                        eprintln!(
                                            "[PEER_ANNOUNCE_DIRECT] Received: wallet={}, peer={}, rep={}",
                                            announce.wallet_address,
                                            announce.peer_id,
                                            announce.reputation
                                        );
                                        if let Ok(p_id) = announce.peer_id.parse::<libp2p::PeerId>() {
                                            wallet_to_peer.insert(announce.wallet_address.clone(), p_id);
                                            peer_to_wallet.insert(p_id, announce.wallet_address.clone());
                                        }
                                        
                                        peer_cache.add_or_update(&announce.peer_id, vec![], true);
                                        if let Some(api_url) = announce.api_url {
                                            peer_cache.update_api_url(&announce.peer_id, api_url, announce.grpc_url);
                                        }
                                        peer_cache.save("peer_cache.json");

                                        let mut manager = ppor_manager.lock().await;
                                        if !manager.reputation_table.contains_key(&announce.wallet_address) {
                                            manager.reputation_table.insert(
                                                announce.wallet_address.clone(),
                                                announce.reputation,
                                            );
                                        }
                                        let seed = format!(
                                            "{}:{}",
                                            manager.last_finalized_hash, manager.current_epoch
                                        );
                                        manager.select_committee_weighted(&seed);
                                        drop(manager);
                                    }
                                    
                                    let _ = swarm
                                        .behaviour_mut()
                                        .request_response
                                        .send_response(
                                            channel,
                                            ConsensusResponse::PeerAnnounceAck { received: true },
                                        );
                                }
                            },
                            libp2p::request_response::Message::Response {
                                request_id: _,
                                response,
                            } => {
                                match response {
                                    ConsensusResponse::TxAck { accepted, reason } => {
                                        eprintln!(
                                            "[TX_RELAY] Got response from validator: accepted={}, reason={}",
                                            accepted, reason
                                        );
                                    }
                                    ConsensusResponse::PbftAck { received } => {
                                        if !received {
                                            eprintln!("[PBFT_DIRECT] Validator did NOT receive our PBFT vote");
                                        }
                                    }
                                    ConsensusResponse::PeerAnnounceAck { received: _ } => {
                                        // Acknowledged, no further action needed
                                    }
                                }
                            }
                        }
                    }

                    // ================================================================
                    // Gossipsub handlers (kept for discovery + backward compat)
                    // ================================================================
                    SwarmEvent::Behaviour(ConsensusBehaviourEvent::Gossipsub(
                        libp2p::gossipsub::Event::Message { message, .. }
                    )) => {
                        let topic = message.topic.as_str();
                        if topic == "feedo_peer_announce" {
                            if let Ok(announce) =
                                serde_json::from_slice::<PeerAnnounce>(&message.data)
                            {
                                eprintln!(
                                    "[PEER_ANNOUNCE] Received: wallet={}, peer={}, rep={}",
                                    announce.wallet_address,
                                    announce.peer_id,
                                    announce.reputation
                                );
                                if let Ok(peer_id) =
                                    announce.peer_id.parse::<libp2p::PeerId>()
                                {
                                    wallet_to_peer
                                        .insert(announce.wallet_address.clone(), peer_id);
                                    peer_to_wallet
                                        .insert(peer_id, announce.wallet_address.clone());
                                }
                                
                                peer_cache.add_or_update(&announce.peer_id, vec![], true);
                                if let Some(api_url) = announce.api_url {
                                    peer_cache.update_api_url(&announce.peer_id, api_url, announce.grpc_url);
                                }
                                peer_cache.save("peer_cache.json");

                                let mut manager = ppor_manager.lock().await;
                                if !manager
                                    .reputation_table
                                    .contains_key(&announce.wallet_address)
                                {
                                    manager.reputation_table.insert(
                                        announce.wallet_address.clone(),
                                        announce.reputation,
                                    );
                                    eprintln!(
                                        "[REPUTATION] Added new node {} with score {}",
                                        announce.wallet_address, announce.reputation
                                    );
                                }
                                let seed = format!(
                                    "{}:{}",
                                    manager.last_finalized_hash, manager.current_epoch
                                );
                                manager.select_committee_weighted(&seed);
                            }
                        } else if topic == "feedo_telemetry" {
                            if let Ok(report) = serde_json::from_slice::<crate::telemetry::TelemetryReport>(&message.data) {
                                let mut cache = telemetry_cache.lock().await;
                                cache.add_report(report);
                                cache.save();
                            }
                        } else if topic == "feedo_consensus_ppor" {
                            // Backward-compat: receive PBFT messages via gossipsub from old nodes.
                            // When direct_mode is active, these are also handled but we
                            // SEND via direct request-response.
                            if let Ok(pbft_msg) =
                                <shared_proto::feedo::PbftMessage as prost::Message>::decode(
                                    &message.data[..],
                                )
                            {
                                // Check if the INCOMING message is already Finalized
                                // BEFORE processing (handle_message returns None for Finalized).
                                let is_finalized = pbft_msg.phase == PbftPhase::Finalized as i32;

                                let mut manager = ppor_manager.lock().await;
                                let committee = manager.current_committee.clone();
                                let my_wallet = manager.node_id.clone();

                                let reply_msg =
                                    manager.handle_message(pbft_msg.clone());
                                if let Some(ref reply) = reply_msg {
                                    if direct_mode {
                                        // Phase 1: send reply via direct request-response
                                        send_pbft_to_committee(
                                            &mut swarm,
                                            reply,
                                            &committee,
                                            &my_wallet,
                                            &wallet_to_peer,
                                        );
                                    } else {
                                        // Backward-compat: publish via gossipsub
                                        let data = prost::Message::encode_to_vec(reply);
                                        let topic = libp2p::gossipsub::IdentTopic::new(
                                            "feedo_consensus_ppor",
                                        );
                                        let _ =
                                            swarm.behaviour_mut().gossipsub.publish(topic, data);
                                    }
                                }

                                // Self-deliver chain
                                let final_msg = self_deliver_pbft_chain(
                                    &mut manager,
                                    reply_msg,
                                    &mut swarm,
                                    &committee,
                                    &my_wallet,
                                    &wallet_to_peer,
                                );

                                // Handle finalized: check both incoming message (for direct Finalized)
                                // and chain result (for self-delivery produced Finalized).
                                if is_finalized {
                                    // The incoming message was itself a Finalized vote — apply it.
                                    handle_finalized_tx(
                                        &pbft_msg,
                                        &mut manager,
                                        &name_db,
                                        &ledger,
                                        &mut pending_name_txs,
                                        &mut pending_cid_txs,
                                        &mut pending_ledger_txs,
                                        &mut pending_metadata_txs,
                                        &mut swarm,
                                    )
                                    .await;
                                }
                                if let Some(ref fmsg) = final_msg {
                                    if fmsg.phase == PbftPhase::Finalized as i32 {
                                        handle_finalized_tx(
                                            fmsg,
                                            &mut manager,
                                            &name_db,
                                            &ledger,
                                            &mut pending_name_txs,
                                            &mut pending_cid_txs,
                                            &mut pending_ledger_txs,
                                            &mut pending_metadata_txs,
                                            &mut swarm,
                                        )
                                        .await;
                                    }
                                }
                                drop(manager);
                            }
                        } else if topic == "feedo_name_txs" {
                            if let Ok(tx) =
                                serde_json::from_slice::<crate::NameRegistrationTx>(&message.data)
                            {
                                // Reject names that do not end with .feedo (security boundary)
                                if !tx.name.ends_with(".feedo") || tx.name.len() <= ".feedo".len() {
                                    eprintln!("[GOSSIP] Rejected name tx (must end with .feedo): {}", tx.name);
                                    continue;
                                }
                                let payload_bytes =
                                    format!("{}{}", tx.name, tx.did).into_bytes();
                                if crate::did::verify_signature(
                                    &tx.public_key,
                                    &payload_bytes,
                                    &tx.signature,
                                ) {
                                    let hash = tx.tx_hash();
                                    pending_name_txs.insert(hash.clone(), tx);
                                    let mut manager = ppor_manager.lock().await;
                                    let committee = manager.current_committee.clone();
                                    let my_wallet = manager.node_id.clone();

                                    let reply_msg = manager.mark_validated(
                                        &hash,
                                        crate::ppor::TX_TYPE_NAME_REGISTRATION,
                                    );
                                    if let Some(ref reply) = reply_msg {
                                        if direct_mode {
                                            send_pbft_to_committee(
                                                &mut swarm,
                                                reply,
                                                &committee,
                                                &my_wallet,
                                                &wallet_to_peer,
                                            );
                                        } else {
                                            let data = prost::Message::encode_to_vec(reply);
                                            let topic = libp2p::gossipsub::IdentTopic::new(
                                                "feedo_consensus_ppor",
                                            );
                                            let _ = swarm
                                                .behaviour_mut()
                                                .gossipsub
                                                .publish(topic, data);
                                        }
                                    }

                                    let final_msg = self_deliver_pbft_chain(
                                        &mut manager,
                                        reply_msg,
                                        &mut swarm,
                                        &committee,
                                        &my_wallet,
                                        &wallet_to_peer,
                                    );

                                    if let Some(ref fmsg) = final_msg {
                                        if fmsg.phase == PbftPhase::Finalized as i32 {
                                            handle_finalized_tx(
                                                fmsg,
                                                &mut manager,
                                                &name_db,
                                                &ledger,
                                                &mut pending_name_txs,
                                                &mut pending_cid_txs,
                                                &mut pending_ledger_txs,
                                                &mut pending_metadata_txs,
                                                &mut swarm,
                                            )
                                            .await;
                                        }
                                    }
                                    drop(manager);
                                }
                            }
                        } else if topic == "feedo_update_cid_txs" {
                            if let Ok(tx) =
                                serde_json::from_slice::<crate::UpdateCidTx>(&message.data)
                            {
                                let hash = tx.tx_hash();
                                pending_cid_txs.insert(hash.clone(), tx);
                                let mut manager = ppor_manager.lock().await;
                                let committee = manager.current_committee.clone();
                                let my_wallet = manager.node_id.clone();

                                let reply_msg = manager.mark_validated(
                                    &hash,
                                    crate::ppor::TX_TYPE_UPDATE_CID,
                                );
                                if let Some(ref reply) = reply_msg {
                                    if direct_mode {
                                        send_pbft_to_committee(
                                            &mut swarm,
                                            reply,
                                            &committee,
                                            &my_wallet,
                                            &wallet_to_peer,
                                        );
                                    } else {
                                        let data = prost::Message::encode_to_vec(reply);
                                        let topic = libp2p::gossipsub::IdentTopic::new(
                                            "feedo_consensus_ppor",
                                        );
                                        let _ =
                                            swarm.behaviour_mut().gossipsub.publish(topic, data);
                                    }
                                }

                                let final_msg = self_deliver_pbft_chain(
                                    &mut manager,
                                    reply_msg,
                                    &mut swarm,
                                    &committee,
                                    &my_wallet,
                                    &wallet_to_peer,
                                );

                                if let Some(ref fmsg) = final_msg {
                                    if fmsg.phase == PbftPhase::Finalized as i32 {
                                        handle_finalized_tx(
                                            fmsg,
                                            &mut manager,
                                            &name_db,
                                            &ledger,
                                            &mut pending_name_txs,
                                            &mut pending_cid_txs,
                                            &mut pending_ledger_txs,
                                            &mut pending_metadata_txs,
                                            &mut swarm,
                                        )
                                        .await;
                                    }
                                }
                                drop(manager);
                            }
                        } else if topic == "feedo_ledger_txs" {
                            if let Ok(tx) =
                                serde_json::from_slice::<crate::LedgerTx>(&message.data)
                            {
                                let hash = tx.tx_hash();
                                pending_ledger_txs.insert(hash.clone(), tx);
                                let mut manager = ppor_manager.lock().await;
                                let committee = manager.current_committee.clone();
                                let my_wallet = manager.node_id.clone();

                                let reply_msg = manager.mark_validated(
                                    &hash,
                                    crate::ppor::TX_TYPE_LEDGER,
                                );
                                if let Some(ref reply) = reply_msg {
                                    if direct_mode {
                                        send_pbft_to_committee(
                                            &mut swarm,
                                            reply,
                                            &committee,
                                            &my_wallet,
                                            &wallet_to_peer,
                                        );
                                    } else {
                                        let data = prost::Message::encode_to_vec(reply);
                                        let topic = libp2p::gossipsub::IdentTopic::new(
                                            "feedo_consensus_ppor",
                                        );
                                        let _ =
                                            swarm.behaviour_mut().gossipsub.publish(topic, data);
                                    }
                                }

                                let final_msg = self_deliver_pbft_chain(
                                    &mut manager,
                                    reply_msg,
                                    &mut swarm,
                                    &committee,
                                    &my_wallet,
                                    &wallet_to_peer,
                                );

                                if let Some(ref fmsg) = final_msg {
                                    if fmsg.phase == PbftPhase::Finalized as i32 {
                                        handle_finalized_tx(
                                            fmsg,
                                            &mut manager,
                                            &name_db,
                                            &ledger,
                                            &mut pending_name_txs,
                                            &mut pending_cid_txs,
                                            &mut pending_ledger_txs,
                                            &mut pending_metadata_txs,
                                            &mut swarm,
                                        )
                                        .await;
                                    }
                                }
                                drop(manager);
                            }
                        } else if topic == "feedo_update_metadata_txs" {
                            if let Ok(tx) =
                                serde_json::from_slice::<crate::UpdateMetadataTx>(&message.data)
                            {
                                let hash = tx.tx_hash();
                                pending_metadata_txs.insert(hash.clone(), tx);
                                let mut manager = ppor_manager.lock().await;
                                let committee = manager.current_committee.clone();
                                let my_wallet = manager.node_id.clone();

                                let reply_msg = manager.mark_validated(
                                    &hash,
                                    crate::ppor::TX_TYPE_UPDATE_METADATA,
                                );
                                if let Some(ref reply) = reply_msg {
                                    if direct_mode {
                                        send_pbft_to_committee(
                                            &mut swarm,
                                            reply,
                                            &committee,
                                            &my_wallet,
                                            &wallet_to_peer,
                                        );
                                    } else {
                                        let data = prost::Message::encode_to_vec(reply);
                                        let topic = libp2p::gossipsub::IdentTopic::new(
                                            "feedo_consensus_ppor",
                                        );
                                        let _ =
                                            swarm.behaviour_mut().gossipsub.publish(topic, data);
                                    }
                                }

                                let final_msg = self_deliver_pbft_chain(
                                    &mut manager,
                                    reply_msg,
                                    &mut swarm,
                                    &committee,
                                    &my_wallet,
                                    &wallet_to_peer,
                                );

                                if let Some(ref fmsg) = final_msg {
                                    if fmsg.phase == PbftPhase::Finalized as i32 {
                                        handle_finalized_tx(
                                            fmsg,
                                            &mut manager,
                                            &name_db,
                                            &ledger,
                                            &mut pending_name_txs,
                                            &mut pending_cid_txs,
                                            &mut pending_ledger_txs,
                                            &mut pending_metadata_txs,
                                            &mut swarm,
                                        )
                                        .await;
                                    }
                                }
                                drop(manager);
                            }
                        }
                    }

                    SwarmEvent::Behaviour(ConsensusBehaviourEvent::Kademlia(event)) => {
                        match event {
                            libp2p::kad::Event::RoutingUpdated {
                                peer,
                                is_new_peer,
                                ..
                            } => {
                                if is_new_peer {
                                    eprintln!(
                                        "Consensus Kademlia DHT discovered a new node: {}",
                                        peer
                                    );
                                }
                            }
                            libp2p::kad::Event::OutboundQueryProgressed { id, result, .. } => {
                                if let Some(tx) = pending_queries.remove(&id) {
                                    let found = match &result {
                                        libp2p::kad::QueryResult::GetRecord(Ok(
                                            libp2p::kad::GetRecordOk::FoundRecord(peer_record),
                                        )) => serde_json::from_slice::<crate::ResolveRes>(
                                            &peer_record.record.value,
                                        )
                                        .ok(),
                                        _ => None,
                                    };
                                    let _ = tx.send(found);
                                }
                                if let Some(tx) = pending_did_queries.remove(&id) {
                                    let found = match &result {
                                        libp2p::kad::QueryResult::GetRecord(Ok(
                                            libp2p::kad::GetRecordOk::FoundRecord(peer_record),
                                        )) => serde_json::from_slice::<crate::did::DidDocument>(
                                            &peer_record.record.value,
                                        )
                                        .ok(),
                                        _ => None,
                                    };
                                    let _ = tx.send(found);
                                }
                                if let Some(tx) = pending_acl_queries.remove(&id) {
                                    let found = match &result {
                                        libp2p::kad::QueryResult::GetRecord(Ok(
                                            libp2p::kad::GetRecordOk::FoundRecord(peer_record),
                                        )) => String::from_utf8(peer_record.record.value.clone()).ok(),
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
                        let manager = ppor_manager.lock().await;
                        let committee = manager.current_committee.clone();
                        let my_wallet = manager.node_id.clone();
                        drop(manager);

                        if direct_mode {
                            // Phase 1: send direct to committee
                            send_pbft_to_committee(
                                &mut swarm,
                                &msg,
                                &committee,
                                &my_wallet,
                                &wallet_to_peer,
                            );
                            // Self-deliver
                            let mut manager = ppor_manager.lock().await;
                            let final_msg = self_deliver_pbft_chain(
                                &mut manager,
                                Some(msg),
                                &mut swarm,
                                &committee,
                                &my_wallet,
                                &wallet_to_peer,
                            );
                            if let Some(ref fmsg) = final_msg {
                                if fmsg.phase == PbftPhase::Finalized as i32 {
                                    handle_finalized_tx(
                                        fmsg,
                                        &mut manager,
                                        &name_db,
                                        &ledger,
                                        &mut pending_name_txs,
                                        &mut pending_cid_txs,
                                        &mut pending_ledger_txs,
                                        &mut pending_metadata_txs,
                                        &mut swarm,
                                    )
                                    .await;
                                }
                            }
                            drop(manager);
                        } else {
                            let data = prost::Message::encode_to_vec(&msg);
                            let topic = libp2p::gossipsub::IdentTopic::new("feedo_consensus_ppor");
                            if let Err(e) = swarm.behaviour_mut().gossipsub.publish(topic, data) {
                                eprintln!("Failed to publish PPoR message: {:?}", e);
                            }
                        }
                    }
                    SwarmCommand::BroadcastNameTx(tx) => {
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
                    SwarmCommand::BroadcastUpdateMetadataTx(tx) => {
                        if let Ok(data) = serde_json::to_vec(&tx) {
                            let topic =
                                libp2p::gossipsub::IdentTopic::new("feedo_update_metadata_txs");
                            if let Err(e) = swarm.behaviour_mut().gossipsub.publish(topic, data) {
                                eprintln!("Failed to publish UpdateMetadataTx: {:?}", e);
                            }
                        }
                    }
                    SwarmCommand::RelayTxToValidators {
                        tx_type,
                        tx_data_json,
                        from_node,
                        signature,
                    } => {
                        let manager = ppor_manager.lock().await;
                        let committee = manager.current_committee.clone();
                        let my_wallet = manager.node_id.clone();
                        drop(manager);

                        let tx_request = ConsensusRequest::TxRelay {
                            tx_type: tx_type.to_string(),
                            tx_data_json,
                            from_node: from_node.clone(),
                            signature,
                        };

                        let mut sent_count = 0u32;
                        for validator_wallet in &committee {
                            if *validator_wallet == my_wallet {
                                continue;
                            }
                            if let Some(&peer_id) = wallet_to_peer.get(validator_wallet) {
                                let _ = swarm
                                    .behaviour_mut()
                                    .request_response
                                    .send_request(&peer_id, tx_request.clone());
                                sent_count += 1;
                                eprintln!(
                                    "[TX_RELAY] Sent to validator {} (peer={})",
                                    validator_wallet, peer_id
                                );
                            }
                        }
                        if sent_count > 0 {
                            eprintln!(
                                "[TX_RELAY] Transaction relayed to {} validators",
                                sent_count
                            );
                        }
                    }
                    SwarmCommand::PublishDidDht(did, doc) => {
                        let record = libp2p::kad::Record {
                            key: libp2p::kad::RecordKey::new(&did),
                            value: serde_json::to_vec(&doc).unwrap(),
                            publisher: None,
                            expires: None,
                        };
                        let _ = swarm
                            .behaviour_mut()
                            .kademlia
                            .put_record(record, libp2p::kad::Quorum::One);
                        eprintln!("Published DID {} to Kademlia DHT", did);
                    }
                    SwarmCommand::LookupDidDht(did, tx) => {
                        let query_id = swarm
                            .behaviour_mut()
                            .kademlia
                            .get_record(libp2p::kad::RecordKey::new(&did));
                        pending_did_queries.insert(query_id, tx);
                        eprintln!("Looking up DID {} in Kademlia DHT", did);
                    }
                    SwarmCommand::PublishAclDht(file_hash, grantee_did, encrypted_key) => {
                        let key_str = format!("acl:{}:{}", file_hash, grantee_did);
                        let record = libp2p::kad::Record {
                            key: libp2p::kad::RecordKey::new(&key_str),
                            value: encrypted_key.into_bytes(),
                            publisher: None,
                            expires: None,
                        };
                        let _ = swarm
                            .behaviour_mut()
                            .kademlia
                            .put_record(record, libp2p::kad::Quorum::One);
                        eprintln!("Published ACL {} to Kademlia DHT", key_str);
                    }
                    SwarmCommand::QueryAclDht(file_hash, grantee_did, tx) => {
                        let key_str = format!("acl:{}:{}", file_hash, grantee_did);
                        let query_id = swarm
                            .behaviour_mut()
                            .kademlia
                            .get_record(libp2p::kad::RecordKey::new(&key_str));
                        pending_acl_queries.insert(query_id, tx);
                        eprintln!("Looking up ACL {} in Kademlia DHT", key_str);
                    }
                    SwarmCommand::PublishDht(name, res) => {
                        let record = libp2p::kad::Record {
                            key: libp2p::kad::RecordKey::new(&name),
                            value: serde_json::to_vec(&res).unwrap(),
                            publisher: None,
                            expires: None,
                        };
                        let _ = swarm
                            .behaviour_mut()
                            .kademlia
                            .put_record(record, libp2p::kad::Quorum::One);
                        eprintln!("Published {} to Kademlia DHT", name);
                    }
                    SwarmCommand::LookupDht(name, tx) => {
                        let query_id = swarm
                            .behaviour_mut()
                            .kademlia
                            .get_record(libp2p::kad::RecordKey::new(&name));
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
                            let _ = swarm
                                .behaviour_mut()
                                .kademlia
                                .put_record(record, libp2p::kad::Quorum::One);
                            eprintln!(
                                "[REPUTATION] Published reputation {}={} to DHT",
                                wallet, reputation
                            );
                        }
                    }

                    // --- Grant System Handlers ---

                    SwarmCommand::CreateGrant { grant, response_tx } => {
                        let mut ppor = ppor_manager.lock().await;
                        let result = ppor.create_grant(grant);
                        drop(ppor);
                        let _ = response_tx.send(result);
                    }

                    SwarmCommand::ClaimGrant { grant_id, did, response_tx } => {
                        let amount;
                        {
                            let mut ppor = ppor_manager.lock().await;
                            match ppor.verify_grant_claim(&grant_id, &did) {
                                Ok(a) => amount = a,
                                Err(e) => {
                                    let _ = response_tx.send(Err(e));
                                    continue;
                                }
                            }
                            match ppor.execute_claim(&grant_id, &did, amount) {
                                Ok(_) => {},
                                Err(e) => {
                                    let _ = response_tx.send(Err(e));
                                    continue;
                                }
                            }
                        }

                        // Нарахувати кредити
                        let new_balance = ledger.claim_grant_credits(&did, amount, &grant_id).await;

                        // Записати в БД
                        {
                            let db = name_db.lock().await;
                            let _ = db.insert_grant_claim(&did, &grant_id, amount, "local");
                        }

                        eprintln!(
                            "[GRANT] Claim processed: grant={}, did={}, amount={}, balance={}",
                            grant_id, did, amount, new_balance
                        );
                        let _ = response_tx.send(Ok((amount, new_balance)));
                    }

                    SwarmCommand::GetGrantInfo { grant_id, response_tx } => {
                        let ppor = ppor_manager.lock().await;
                        let info = ppor.grant_programs.get(&grant_id).map(|g| GrantInfoResponse {
                            grant_id: g.grant_id.clone(),
                            title: g.title.clone(),
                            verification: g.verification.to_str().to_string(),
                            amount_per_claim: g.amount_per_claim,
                            max_claims: g.max_claims,
                            claimed_count: g.claimed_count,
                            claimed_total: g.claimed_total,
                            active: g.active,
                            expires_at: g.expires_at,
                            created_at: g.created_at,
                        });
                        drop(ppor);
                        let _ = response_tx.send(info);
                    }

                    SwarmCommand::ListGrants { response_tx } => {
                        let ppor = ppor_manager.lock().await;
                        let grants: Vec<GrantInfoResponse> = ppor
                            .grant_programs
                            .values()
                            .map(|g| GrantInfoResponse {
                                grant_id: g.grant_id.clone(),
                                title: g.title.clone(),
                                verification: g.verification.to_str().to_string(),
                                amount_per_claim: g.amount_per_claim,
                                max_claims: g.max_claims,
                                claimed_count: g.claimed_count,
                                claimed_total: g.claimed_total,
                                active: g.active,
                                expires_at: g.expires_at,
                                created_at: g.created_at,
                            })
                            .collect();
                        drop(ppor);
                        let _ = response_tx.send(grants);
                    }
                }
            }
            // Proactive epoch rotation check every 5 seconds.
            // This ensures epoch progresses even without PBFT traffic (critical for tests).
            _ = epoch_tick.tick() => {
                let mut manager = ppor_manager.lock().await;
                let old_epoch = manager.current_epoch;
                manager.maybe_rotate_epoch();
                if manager.current_epoch != old_epoch {
                    let new_epoch = manager.current_epoch;
                    let signer = manager.node_id.clone();
                    let secret_key = manager.secret_key.clone();
                    eprintln!(
                        "[EPOCH_TICK] Proactive rotation: epoch {} -> {}",
                        old_epoch, new_epoch
                    );

                    // Phase 1.5: Generate and publish state snapshot
                    let full_records = {
                        let db = name_db.lock().await;
                        db.get_all_records_full().unwrap_or_default()
                    };
                    let snapshot = ledger.generate_state_snapshot(
                        new_epoch,
                        full_records,
                        &signer,
                        secret_key.as_ref(),
                    ).await;

                    // Publish snapshot to DHT
                    if let Ok(snapshot_json) = serde_json::to_vec(&snapshot) {
                        let snapshot_key = format!("/snapshot/{}", new_epoch);
                        let record = libp2p::kad::Record {
                            key: libp2p::kad::RecordKey::new(&snapshot_key),
                            value: snapshot_json,
                            publisher: None,
                            expires: None,
                        };
                        let _ = swarm.behaviour_mut().kademlia.put_record(record, libp2p::kad::Quorum::One);
                        eprintln!(
                            "[SNAPSHOT] Published snapshot epoch={}, {} names, {} balances, merkle_root={}",
                            new_epoch, snapshot.names.len(), snapshot.balances.len(),
                            &snapshot.merkle_root[..16.min(snapshot.merkle_root.len())]
                        );
                    }

                    // Phase 1.5: Garbage collection — archive finalized states,
                    // then clean up entries older than 2 epochs.
                    manager.cleanup_finalized_states(2);

                    // Re-publish all known names to DHT with the new epoch
                    // so that resolve responses reflect the current epoch.
                    drop(manager);
                    let db = name_db.lock().await;
                    if let Ok(records) = db.get_all_records() {
                        let count = records.len();
                        for (name, did, cid, gateways_json) in records {
                            let gateways = gateways_json.and_then(|j| serde_json::from_str::<Vec<String>>(&j).ok());
                            let finalized_at = std::time::SystemTime::now()
                                .duration_since(std::time::UNIX_EPOCH)
                                .unwrap()
                                .as_secs();
                            let res = crate::ResolveRes {
                                did: did.clone(),
                                cid: cid.clone(),
                                gateways,
                                epoch: Some(new_epoch),
                                finalized_at: Some(finalized_at),
                                title: None,
                                description: None,
                                icon_cid: None,
                                created_at: None,
                                updated_at: Some(finalized_at as i64),
                            };
                            let record = libp2p::kad::Record {
                                key: libp2p::kad::RecordKey::new(&name),
                                value: serde_json::to_vec(&res).unwrap(),
                                publisher: None,
                                expires: None,
                            };
                            let _ = swarm.behaviour_mut().kademlia.put_record(record, libp2p::kad::Quorum::One);
                        }
                        if count > 0 {
                            eprintln!("[EPOCH_TICK] Re-published {} names to DHT with epoch {}", count, new_epoch);
                        }
                    }
                } else {
                    drop(manager);
                }
            }
            _ = telemetry_tick.tick() => {
                let node_id = swarm.local_peer_id().to_string();
                let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
                let stats = crate::telemetry::TelemetryStats {
                    storage_used_bytes: 0,
                    total_requests: 0,
                    vectors_processed: 0,
                    pbft_votes_processed: 0, // In future, extract from ppor_manager
                    blocks_finalized: 0,     // In future, extract from ppor_manager
                };
                let report = crate::telemetry::TelemetryReport {
                    node_id,
                    node_type: "consensus".to_string(),
                    timestamp: now,
                    stats,
                };
                if let Ok(data) = serde_json::to_vec(&report) {
                    let topic = libp2p::gossipsub::IdentTopic::new("feedo_telemetry");
                    let _ = swarm.behaviour_mut().gossipsub.publish(topic, data);
                }
            }
            _ = announce_tick.tick() => {
                let manager = ppor_manager.lock().await;
                let my_peer_id = swarm.local_peer_id().to_string();
                let my_wallet = manager.node_id.clone();
                let my_reputation = manager
                    .reputation_table
                    .get(&my_wallet)
                    .copied()
                    .unwrap_or(10);
                drop(manager);
                let announce = PeerAnnounce {
                    peer_id: my_peer_id.clone(),
                    wallet_address: my_wallet.clone(),
                    reputation: my_reputation,
                    version: "1.0.0".to_string(),
                    api_url: Some(http_url.clone()),
                    grpc_url: Some(grpc_url.clone()),
                };
                if let Ok(data) = serde_json::to_vec(&announce) {
                    let topic = libp2p::gossipsub::IdentTopic::new("feedo_peer_announce");
                    let _ = swarm.behaviour_mut().gossipsub.publish(topic, data);
                    
                    if let Ok(announce_json) = serde_json::to_string(&announce) {
                        let request = ConsensusRequest::PeerAnnounce { announce_json };
                        let peers: Vec<_> = swarm.connected_peers().copied().collect();
                        for p in peers {
                            swarm.behaviour_mut().request_response.send_request(&p, request.clone());
                        }
                    }
                }
            }
        }
    }
}
