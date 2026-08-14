use axum::{routing::{get, post}, Router, Json, extract::{State, Path}};
use serde::{Deserialize, Serialize};
use std::time::{SystemTime, UNIX_EPOCH};
use shared_proto::consensus::consensus_service_server::{ConsensusService, ConsensusServiceServer};
use shared_proto::consensus::{
    Empty, MissingChunkRequest, MissingChunkResponse, ResolveNameRequest,
    ResolveNameResponse, ValidatorList, VerifyUploadRequest, VerifyUploadResponse, VerifyDownloadRequest, VerifyDownloadResponse,
};
use tonic::{transport::Server, Request, Response, Status};
use std::net::SocketAddr;

use std::sync::Arc;
use tokio::sync::Mutex;
use libp2p::{SwarmBuilder, PeerId, gossipsub};
use std::time::Duration;
use tokio::sync::mpsc;

pub mod accounting;
pub mod authority;
pub mod did;
pub mod eth_bridge;
pub mod name_db;
pub mod ppor;
pub mod network;
pub mod swarm_loop;
pub mod replay;
pub mod acl;
pub mod peer_cache;
pub mod telemetry;
pub mod dht_store;

use swarm_loop::SwarmCommand;
use network::{ConsensusCodec, CONSENSUS_PROTOCOL};
use authority::GrantAuthority;

pub struct MyConsensusService {
    ledger: Arc<accounting::Ledger>,
    did_manager: Arc<Mutex<did::DidManager>>,
    eth_bridge: Arc<eth_bridge::Web3Bridge>,
    name_db: Arc<Mutex<name_db::NameDb>>,
    ppor_manager: Arc<Mutex<ppor::PporManager>>,
    swarm_tx: mpsc::UnboundedSender<SwarmCommand>,
    acl_manager: Arc<acl::AclManager>,
}

#[tonic::async_trait]
impl ConsensusService for MyConsensusService {
    async fn verify_upload_rights(
        &self,
        request: Request<VerifyUploadRequest>,
    ) -> Result<Response<VerifyUploadResponse>, Status> {
        let req = request.into_inner();
        eprintln!("VerifyUploadRequest: did={}, hash={}", req.user_did, req.file_hash);
        
        let balance = self.ledger.get_balance(&req.user_did).await;
        let did_manager = self.did_manager.lock().await;
        if did_manager.get_document(&req.user_did).is_some() {
            if balance > 0 {
                return Ok(Response::new(VerifyUploadResponse {
                    is_allowed: true,
                    reason: "Ok".into(),
                }));
            } else {
                return Ok(Response::new(VerifyUploadResponse {
                    is_allowed: false,
                    reason: "Insufficient balance".into(),
                }));
            }
        }
        
        Ok(Response::new(VerifyUploadResponse {
            is_allowed: false,
            reason: "DID not found".into(),
        }))
    }

    async fn verify_download_rights(
        &self,
        request: Request<VerifyDownloadRequest>,
    ) -> Result<Response<VerifyDownloadResponse>, Status> {
        let req = request.into_inner();
        eprintln!("VerifyDownloadRequest: did={}, hash={}", req.user_did, req.file_hash);
        
        let did_manager = self.did_manager.lock().await;
        let doc = did_manager.get_document(&req.user_did);
        drop(did_manager);
        
        if let Some(doc) = doc {
            let pub_key = &doc.verification_method[0].public_key_multibase;
            let payload_bytes = format!("{}{}", req.file_hash, req.user_did).into_bytes();
            if !did::verify_signature(pub_key, &payload_bytes, &req.signature) {
                return Ok(Response::new(VerifyDownloadResponse {
                    is_allowed: false,
                    encrypted_symmetric_key: "".into(),
                    reason: "Invalid signature".into(),
                }));
            }
            
            if let Some(encrypted_key) = self.acl_manager.get_encrypted_key(&req.file_hash, &req.user_did) {
                return Ok(Response::new(VerifyDownloadResponse {
                    is_allowed: true,
                    encrypted_symmetric_key: encrypted_key,
                    reason: "Ok".into(),
                }));
            } else {
                return Ok(Response::new(VerifyDownloadResponse {
                    is_allowed: false,
                    encrypted_symmetric_key: "".into(),
                    reason: "Access denied".into(),
                }));
            }
        }
        
        Ok(Response::new(VerifyDownloadResponse {
            is_allowed: false,
            encrypted_symmetric_key: "".into(),
            reason: "DID not found".into(),
        }))
    }

    async fn report_missing_chunk(
        &self,
        _request: Request<MissingChunkRequest>,
    ) -> Result<Response<MissingChunkResponse>, Status> {
        Ok(Response::new(MissingChunkResponse { reported: true }))
    }

    async fn get_active_validators(
        &self,
        _request: Request<Empty>,
    ) -> Result<Response<ValidatorList>, Status> {
        Ok(Response::new(ValidatorList { validators: vec![] }))
    }

    async fn resolve_name(
        &self,
        request: Request<ResolveNameRequest>,
    ) -> Result<Response<ResolveNameResponse>, Status> {
        let req = request.into_inner();
        let name_db = self.name_db.lock().await;
        if let Ok(Some((_, Some(hash), _))) = name_db.resolve_name(&req.name) {
            Ok(Response::new(ResolveNameResponse {
                file_hash: hash,
                found: true,
            }))
        } else {
            Ok(Response::new(ResolveNameResponse {
                file_hash: "".into(),
                found: false,
            }))
        }
    }
}

#[derive(Clone)]
pub struct AppState {
    pub name_db: Arc<Mutex<name_db::NameDb>>,
    pub did_manager: Arc<Mutex<did::DidManager>>,
    pub swarm_tx: mpsc::UnboundedSender<SwarmCommand>,
    pub ledger: Arc<accounting::Ledger>,
    pub ppor_manager: Arc<Mutex<ppor::PporManager>>,
    pub grant_authority: Arc<authority::CommitteeGrantAuthority>,
    pub acl_manager: Arc<acl::AclManager>,
    pub telemetry_cache: Arc<Mutex<telemetry::TelemetryCache>>,
}

#[derive(Deserialize)]
pub struct DidRegisterReq { 
    pub did: String,
    pub public_key: String 
}

#[derive(Serialize)]
pub struct DidRegisterRes { pub did: String }

#[derive(Deserialize)]
pub struct NameRegisterReq {
    pub name: String,
    pub did: String,
    pub public_key: String,
    pub signature: String,
}

#[derive(Serialize)]
pub struct NameRegisterRes {
    pub success: bool,
    pub error: Option<String>,
}

#[derive(Deserialize)]
pub struct UpdateCidReq {
    pub name: String,
    pub cid: String,
    pub signature: String,
    pub gateways: Vec<String>,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct NameRegistrationTx {
    pub name: String,
    pub did: String,
    pub public_key: String,
    pub signature: String,
}
impl NameRegistrationTx {
    pub fn tx_hash(&self) -> String {
        use sha2::{Sha256, Digest};
        let mut hasher = Sha256::new();
        hasher.update(format!("{}{}{}", self.name, self.did, self.signature));
        hex::encode(hasher.finalize())
    }
}

#[derive(Serialize, Deserialize, Clone)]
pub struct UpdateCidTx {
    pub name: String,
    pub cid: String,
    pub signature: String,
    pub gateways: Vec<String>,
}
impl UpdateCidTx {
    pub fn tx_hash(&self) -> String {
        use sha2::{Sha256, Digest};
        let mut hasher = Sha256::new();
        hasher.update(format!("{}{}{}", self.name, self.cid, self.signature));
        hex::encode(hasher.finalize())
    }
}

#[derive(Serialize, Deserialize, Clone)]
pub struct LedgerTx {
    pub did: String,
    pub amount: u64,
    pub is_credit: bool,
    pub signature: String,
}
impl LedgerTx {
    pub fn tx_hash(&self) -> String {
        use sha2::{Sha256, Digest};
        let mut hasher = Sha256::new();
        hasher.update(format!("{}{}{}{}", self.did, self.amount, self.is_credit, self.signature));
        hex::encode(hasher.finalize())
    }
}

/// Entry for a single name in a state snapshot.
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct NameSnapshotEntry {
    pub name: String,
    pub did: String,
    pub cid: Option<String>,
    pub gateways: Option<Vec<String>>,
    pub title: Option<String>,
    pub description: Option<String>,
    pub icon_cid: Option<String>,
    pub created_at: Option<i64>,
    pub updated_at: Option<i64>,
}

/// Full state snapshot published to DHT at each epoch rotation.
/// Contains the minimal set of data needed for a new node to bootstrap
/// without replaying the entire transaction history.
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct StateSnapshot {
    pub epoch: u64,
    /// Sorted list of (wallet_address, balance).
    pub balances: Vec<(String, u64)>,
    /// All active registered names with their metadata.
    pub names: Vec<NameSnapshotEntry>,
    /// Hex-encoded Merkle root of the balances (Keccak256 tree).
    pub merkle_root: String,
    /// UNIX timestamp when this snapshot was created.
    pub created_at: u64,
    /// secp256k1 signature of the validator who produced this snapshot.
    pub signature: String,
    /// Wallet address of the signing validator (for signature verification).
    pub signer: String,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct ResolveRes {
    pub did: String,
    pub cid: Option<String>,
    pub gateways: Option<Vec<String>>,
    pub epoch: Option<u64>,
    pub finalized_at: Option<u64>,
    pub title: Option<String>,
    pub description: Option<String>,
    pub icon_cid: Option<String>,
    pub created_at: Option<i64>,
    pub updated_at: Option<i64>,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct UpdateMetadataTx {
    pub name: String,
    pub title: Option<String>,
    pub description: Option<String>,
    pub icon_cid: Option<String>,
    pub signature: String,
}
impl UpdateMetadataTx {
    pub fn tx_hash(&self) -> String {
        use sha2::{Sha256, Digest};
        let mut hasher = Sha256::new();
        hasher.update(format!("{}{}{}{}{}", self.name, self.title.as_deref().unwrap_or(""), self.description.as_deref().unwrap_or(""), self.icon_cid.as_deref().unwrap_or(""), self.signature));
        hex::encode(hasher.finalize())
    }
}

#[derive(Deserialize)]
pub struct GrantFileAccessReq {
    pub file_hash: String,
    pub grantee_did: String,
    pub encrypted_symmetric_key: String,
    pub public_key: String,
    pub signature: String,
}

async fn grant_file_access(State(state): State<AppState>, Json(payload): Json<GrantFileAccessReq>) -> Json<NameRegisterRes> {
    let payload_bytes = format!("{}{}{}", payload.file_hash, payload.grantee_did, payload.encrypted_symmetric_key).into_bytes();
    if !did::verify_signature(&payload.public_key, &payload_bytes, &payload.signature) {
        return Json(NameRegisterRes { success: false, error: Some("Invalid signature".into()) });
    }
    
    // We assume the granter is self (owner) or we just allow anyone to grant access to anyone?
    // For simplicity, we just save the grant.
    if let Err(e) = state.acl_manager.grant_access(&payload.file_hash, &payload.grantee_did, &payload.encrypted_symmetric_key) {
        return Json(NameRegisterRes { success: false, error: Some(e.to_string()) });
    }
    
    let _ = state.swarm_tx.send(SwarmCommand::PublishAclDht(
        payload.file_hash.clone(),
        payload.grantee_did.clone(),
        payload.encrypted_symmetric_key.clone(),
    ));
    
    Json(NameRegisterRes { success: true, error: None })
}

#[derive(Serialize)]
pub struct GetFileAccessRes {
    pub encrypted_symmetric_key: Option<String>,
}

async fn get_file_access(State(state): State<AppState>, Path((file_hash, grantee_did)): Path<(String, String)>) -> Json<GetFileAccessRes> {
    if let Some(key) = state.acl_manager.get_encrypted_key(&file_hash, &grantee_did) {
        return Json(GetFileAccessRes { encrypted_symmetric_key: Some(key) });
    }
    
    // DHT query
    let (tx, rx) = tokio::sync::oneshot::channel();
    let _ = state.swarm_tx.send(SwarmCommand::QueryAclDht(file_hash.clone(), grantee_did.clone(), tx));
    let key = match tokio::time::timeout(std::time::Duration::from_secs(10), rx).await {
        Ok(Ok(Some(k))) => {
            // Cache it locally so we don't have to query again
            let _ = state.acl_manager.grant_access(&file_hash, &grantee_did, &k);
            Some(k)
        },
        _ => None,
    };
    
    Json(GetFileAccessRes { encrypted_symmetric_key: key })
}

async fn register_did(State(state): State<AppState>, Json(payload): Json<DidRegisterReq>) -> Json<DidRegisterRes> {
    let ts = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
    let did_id = payload.did.clone();
    let doc = did::DidDocument::new(did_id.clone(), payload.public_key.clone(), ts);
    let did_manager = state.did_manager.lock().await;
    let _ = did_manager.insert_document(&doc);
    drop(did_manager);

    // Credit immediately locally so the user can use credits right away.
    // The broadcast via consensus is a background operation.
    state.ledger.credit(&did_id, 500000).await;
    let tx = LedgerTx {
        did: did_id.clone(),
        amount: 500000,
        is_credit: true,
        signature: "SYSTEM".to_string(),
    };
    let _ = state.swarm_tx.send(SwarmCommand::BroadcastLedgerTx(tx));

    let _ = state.swarm_tx.send(SwarmCommand::PublishDidDht(did_id.clone(), doc));
    Json(DidRegisterRes { did: did_id })
}

/// Returns true if the name ends with ".feedo" and is longer than just ".feedo".
/// Allows subdomains (e.g. "sub.test.feedo" is valid).
fn is_valid_feedo_name(name: &str) -> bool {
    name.ends_with(".feedo") && name.len() > ".feedo".len()
}

async fn register_name(State(state): State<AppState>, Json(payload): Json<NameRegisterReq>) -> Json<NameRegisterRes> {
    eprintln!("[REGISTER_NAME] Received: name={}, did={}, public_key={}", payload.name, payload.did, payload.public_key);
    
    if !is_valid_feedo_name(&payload.name) {
        eprintln!("[REGISTER_NAME] Invalid name (must end with .feedo): {}", payload.name);
        return Json(NameRegisterRes { success: false, error: Some("Name must end with .feedo".into()) });
    }
    
    let payload_bytes = format!("{}{}", payload.name, payload.did).into_bytes();
    if !did::verify_signature(&payload.public_key, &payload_bytes, &payload.signature) {
        eprintln!("[REGISTER_NAME] Signature INVALID for name={}, sig_len={}", payload.name, payload.signature.len());
        return Json(NameRegisterRes { success: false, error: Some("Invalid signature".into()) });
    }
    eprintln!("[REGISTER_NAME] Signature VALID for name={}", payload.name);

    let name_db = state.name_db.lock().await;
    if name_db.name_exists(&payload.name).unwrap_or(false) {
        eprintln!("[REGISTER_NAME] Name already exists: {}", payload.name);
        return Json(NameRegisterRes { success: false, error: Some("Name already exists".into()) });
    }
    drop(name_db);

    let mut resolved_doc = None;
    let did_manager = state.did_manager.lock().await;
    if let Some(doc) = did_manager.get_document(&payload.did) {
        resolved_doc = Some(doc);
    }
    drop(did_manager);

    if resolved_doc.is_none() {
        let (tx, rx) = tokio::sync::oneshot::channel();
        if state.swarm_tx.send(SwarmCommand::LookupDidDht(payload.did.clone(), tx)).is_ok() {
            if let Ok(Some(doc)) = rx.await {
                let did_manager = state.did_manager.lock().await;
                let _ = did_manager.insert_document(&doc);
                resolved_doc = Some(doc);
            }
        }
    }

    if let Some(_doc) = resolved_doc {
        let local_ledger_balance = state.ledger.get_balance(&payload.did).await;
        if local_ledger_balance < 100 {
            return Json(NameRegisterRes { success: false, error: Some("Insufficient credits".into()) });
        }

        let tx = NameRegistrationTx {
            name: payload.name.clone(),
            did: payload.did.clone(),
            public_key: payload.public_key.clone(),
            signature: payload.signature.clone(),
        };
        
        let _ = state.swarm_tx.send(SwarmCommand::BroadcastNameTx(tx));

        // Write locally immediately AND publish to DHT for other nodes
        {
            let name_db = state.name_db.lock().await;
            let _ = name_db.insert_name(&payload.name, &payload.did, &payload.public_key);
            drop(name_db);
        }
        let res = ResolveRes {
            did: payload.did.clone(),
            cid: None,
            gateways: None,
            epoch: Some(0),
            finalized_at: Some(SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs()),
            title: None,
            description: None,
            icon_cid: None,
            created_at: Some(SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs() as i64),
            updated_at: None,
        };
        let _ = state.swarm_tx.send(SwarmCommand::PublishDht(payload.name.clone(), res));
        
        return Json(NameRegisterRes { success: true, error: None });
    }

    Json(NameRegisterRes { success: false, error: Some("DID not found".into()) })
}

async fn update_cid(State(state): State<AppState>, Json(payload): Json<UpdateCidReq>) -> Json<NameRegisterRes> {
    let mut resolved_did_id = None;
    
    let name_db = state.name_db.lock().await;
    if let Ok(Some((did_id, _, _))) = name_db.resolve_name(&payload.name) {
        resolved_did_id = Some(did_id);
    }
    drop(name_db);
    
    if resolved_did_id.is_none() {
        let (tx, rx) = tokio::sync::oneshot::channel();
        if state.swarm_tx.send(SwarmCommand::LookupDht(payload.name.clone(), tx)).is_ok() {
            if let Ok(Some(res)) = rx.await {
                let name_db = state.name_db.lock().await;
                let gateways_json = res.gateways.as_ref().map(|g| serde_json::to_string(g).unwrap_or_else(|_| "[]".to_string()));
                let _ = name_db.insert_name(&payload.name, &res.did, "");
                if let Some(cid) = &res.cid {
                    let _ = name_db.update_cid(&payload.name, cid, &gateways_json.unwrap_or_else(|| "[]".to_string()));
                }
                drop(name_db);
                resolved_did_id = Some(res.did);
            }
        }
    }
    
    if let Some(did_id) = resolved_did_id {
        let mut resolved_doc = None;
        let did_manager = state.did_manager.lock().await;
        if let Some(doc) = did_manager.get_document(&did_id) {
            resolved_doc = Some(doc);
        }
        drop(did_manager);
        
        if resolved_doc.is_none() {
            let (tx, rx) = tokio::sync::oneshot::channel();
            if state.swarm_tx.send(SwarmCommand::LookupDidDht(did_id.clone(), tx)).is_ok() {
                if let Ok(Some(doc)) = rx.await {
                    let did_manager = state.did_manager.lock().await;
                    let _ = did_manager.insert_document(&doc);
                    resolved_doc = Some(doc);
                }
            }
        }

        if let Some(doc) = resolved_doc {
            let pub_key = &doc.verification_method[0].public_key_multibase;
            let payload_bytes = format!("{}{}", payload.name, payload.cid).into_bytes();
            if !did::verify_signature(pub_key, &payload_bytes, &payload.signature) {
                return Json(NameRegisterRes { success: false, error: Some("Invalid signature".into()) });
            }
            
            let tx = UpdateCidTx {
                name: payload.name.clone(),
                cid: payload.cid.clone(),
                signature: payload.signature.clone(),
                gateways: payload.gateways.clone(),
            };
            
            let _ = state.swarm_tx.send(SwarmCommand::BroadcastUpdateCidTx(tx));

            // Write locally immediately AND publish to DHT
            {
                let name_db = state.name_db.lock().await;
                let gateways_json = serde_json::to_string(&payload.gateways).unwrap_or_else(|_| "[]".to_string());
                let _ = name_db.update_cid(&payload.name, &payload.cid, &gateways_json);
                drop(name_db);
            }
            let res = ResolveRes {
                did: did_id,
                cid: Some(payload.cid.clone()),
                gateways: Some(payload.gateways.clone()),
                epoch: Some(0),
                finalized_at: Some(SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs()),
                title: None,
                description: None,
                icon_cid: None,
                created_at: None,
                updated_at: Some(SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs() as i64),
            };
            let _ = state.swarm_tx.send(SwarmCommand::PublishDht(payload.name.clone(), res));
            
            return Json(NameRegisterRes { success: true, error: None });
        }
    }
    Json(NameRegisterRes { success: false, error: Some("Name not found or DID missing".into()) })
}

async fn resolve_name_http(State(state): State<AppState>, Path(name): Path<String>) -> Json<Option<ResolveRes>> {
    let name_db = state.name_db.lock().await;
    let local_tuple = name_db.resolve_name(&name).ok().flatten();
    drop(name_db);

    // Always try DHT to get the latest data (may have newer CID/gateways)
    let dht_res = {
        let (tx, rx) = tokio::sync::oneshot::channel();
        if state.swarm_tx.send(SwarmCommand::LookupDht(name.clone(), tx)).is_ok() {
            rx.await.ok().flatten()
        } else {
            None
        }
    };

    eprintln!("[RESOLVE] name={}, local={:?}, dht={:?}", name, local_tuple, dht_res);

    match (local_tuple, dht_res) {
        (Some((local_did, local_cid, local_gw_json)), Some(dht)) => {
            // Merge: pick the record with newer finalized_at timestamp
            // If local has no CID but DHT does, use DHT data (stale->fresh upgrade)
            let use_dht = match (&local_cid, &dht.cid) {
                (None, Some(_)) => true,  // DHT has CID, local doesn't
                (Some(_), None) => false, // Local has CID, DHT doesn't
                (None, None) | (Some(_), Some(_)) => {
                    // Both have or both don't have CID: compare finalized_at
                    dht.finalized_at.unwrap_or(0) > 0
                }
            };

            let (did, cid, gateways, epoch, finalized_at) = if use_dht {
                // Update local cache with fresher DHT data
                let db = state.name_db.lock().await;
                if let Some(ref c) = dht.cid {
                    let gw_json = dht.gateways.as_ref()
                        .map(|g| serde_json::to_string(g).unwrap_or_else(|_| "[]".to_string()))
                        .unwrap_or_else(|| "[]".to_string());
                    let _ = db.update_cid(&name, c, &gw_json);
                }
                drop(db);
                (dht.did, dht.cid, dht.gateways, dht.epoch, dht.finalized_at)
            } else {
                let gateways = local_gw_json.as_ref().and_then(|j| serde_json::from_str::<Vec<String>>(j).ok());
                (local_did, local_cid, gateways, None, None)
            };

            Json(Some(ResolveRes { did, cid, gateways, epoch, finalized_at, title: dht.title, description: dht.description, icon_cid: dht.icon_cid, created_at: dht.created_at, updated_at: dht.updated_at }))
        }
        (Some((local_did, local_cid, local_gw_json)), None) => {
            let gateways = local_gw_json.and_then(|json| serde_json::from_str(&json).ok());
            Json(Some(ResolveRes { did: local_did, cid: local_cid, gateways, epoch: None, finalized_at: None, title: None, description: None, icon_cid: None, created_at: None, updated_at: None }))
        }
        (None, Some(dht)) => {
            // Cache DHT data locally
            let db = state.name_db.lock().await;
            let _ = db.insert_name(&name, &dht.did, "");
            if let Some(cid) = &dht.cid {
                let gateways_json = dht.gateways.as_ref()
                    .map(|g| serde_json::to_string(g).unwrap_or_else(|_| "[]".to_string()))
                    .unwrap_or_else(|| "[]".to_string());
                let _ = db.update_cid(&name, cid, &gateways_json);
            }
            drop(db);
            Json(Some(dht))
        }
        (None, None) => Json(None),
    }
}

async fn resolve_cid_http(State(state): State<AppState>, Path(cid): Path<String>) -> Json<Option<String>> {
    let name_db = state.name_db.lock().await;
    if let Ok(Some(name)) = name_db.resolve_cid(&cid) {
        return Json(Some(name));
    }
    Json(None)
}

#[derive(Serialize)]
pub struct BalanceRes {
    pub balance_credits: u64,
}

async fn get_did_balance(State(state): State<AppState>, Path(did): Path<String>) -> Json<Option<BalanceRes>> {
    // Normalize: accept both "0xAddress" and "did:feedo:0xAddress" formats
    let normalized_did = if did.starts_with("did:feedo:") {
        did.clone()
    } else {
        format!("did:feedo:{}", did)
    };
    let balance = state.ledger.get_balance(&normalized_did).await;
    let did_manager = state.did_manager.lock().await;
    if did_manager.get_document(&normalized_did).is_none() && balance == 0 {
        return Json(None);
    }
    drop(did_manager);

    Json(Some(BalanceRes {
        balance_credits: balance,
    }))
}

#[derive(Deserialize)]
pub struct StorageOpReq {
    pub did: String,
    pub bytes: u64,
}

#[derive(Serialize)]
pub struct StorageUsageRes {
    pub did: String,
    pub used_bytes: u64,
    pub max_bytes: u64,
}

async fn reserve_storage_http(
    State(state): State<AppState>,
    Json(req): Json<StorageOpReq>,
) -> Result<Json<StorageUsageRes>, (axum::http::StatusCode, String)> {
    let did = if req.did.starts_with("did:feedo:") {
        req.did.clone()
    } else {
        format!("did:feedo:{}", req.did)
    };
    match state.ledger.reserve_storage(&did, req.bytes).await {
        Ok(used) => {
            let (_, max) = state.ledger.get_storage_usage(&did).await;
            Ok(Json(StorageUsageRes { did, used_bytes: used, max_bytes: max }))
        }
        Err(e) => Err((axum::http::StatusCode::INSUFFICIENT_STORAGE, e)),
    }
}

async fn release_storage_http(
    State(state): State<AppState>,
    Json(req): Json<StorageOpReq>,
) -> Json<StorageUsageRes> {
    let did = if req.did.starts_with("did:feedo:") {
        req.did.clone()
    } else {
        format!("did:feedo:{}", req.did)
    };
    state.ledger.release_storage(&did, req.bytes).await;
    let (used, max) = state.ledger.get_storage_usage(&did).await;
    Json(StorageUsageRes { did, used_bytes: used, max_bytes: max })
}

async fn get_storage_usage_http(
    State(state): State<AppState>,
    Path(did): Path<String>,
) -> Json<StorageUsageRes> {
    let did = if did.starts_with("did:feedo:") {
        did.clone()
    } else {
        format!("did:feedo:{}", did)
    };
    let (used, max) = state.ledger.get_storage_usage(&did).await;
    Json(StorageUsageRes { did, used_bytes: used, max_bytes: max })
}

#[derive(Deserialize)]
pub struct UpdateMetadataReq {
    pub name: String,
    pub title: Option<String>,
    pub description: Option<String>,
    pub icon_cid: Option<String>,
    pub public_key: String,
    pub signature: String,
}

async fn update_metadata(State(state): State<AppState>, Json(payload): Json<UpdateMetadataReq>) -> Json<NameRegisterRes> {
    let mut resolved_did_id = None;

    let name_db = state.name_db.lock().await;
    if let Ok(Some((did_id, _, _))) = name_db.resolve_name(&payload.name) {
        resolved_did_id = Some(did_id);
    }
    drop(name_db);

    if resolved_did_id.is_none() {
        return Json(NameRegisterRes { success: false, error: Some("Name not found".into()) });
    }

    let did_id = resolved_did_id.unwrap();
    let mut resolved_doc = None;
    let did_manager = state.did_manager.lock().await;
    if let Some(doc) = did_manager.get_document(&did_id) {
        resolved_doc = Some(doc);
    }
    drop(did_manager);

    if resolved_doc.is_none() {
        let (tx, rx) = tokio::sync::oneshot::channel();
        if state.swarm_tx.send(SwarmCommand::LookupDidDht(did_id.clone(), tx)).is_ok() {
            if let Ok(Some(doc)) = rx.await {
                let did_manager = state.did_manager.lock().await;
                let _ = did_manager.insert_document(&doc);
                resolved_doc = Some(doc);
            }
        }
    }

    if let Some(doc) = resolved_doc {
        let pub_key = &doc.verification_method[0].public_key_multibase;
        let payload_bytes = format!("{}{}{}{}", payload.name, payload.title.as_deref().unwrap_or(""), payload.description.as_deref().unwrap_or(""), payload.icon_cid.as_deref().unwrap_or("")).into_bytes();
        if !did::verify_signature(pub_key, &payload_bytes, &payload.signature) {
            return Json(NameRegisterRes { success: false, error: Some("Invalid signature".into()) });
        }

        let tx = UpdateMetadataTx {
            name: payload.name.clone(),
            title: payload.title.clone(),
            description: payload.description.clone(),
            icon_cid: payload.icon_cid.clone(),
            signature: payload.signature.clone(),
        };

        let _ = state.swarm_tx.send(SwarmCommand::BroadcastUpdateMetadataTx(tx));

        // Write locally immediately
        {
            let name_db = state.name_db.lock().await;
            let _ = name_db.update_metadata(&payload.name, &payload.title, &payload.description, &payload.icon_cid);
            drop(name_db);
        }
        // Publish updated metadata to DHT
        let res = ResolveRes {
            did: did_id,
            cid: None,
            gateways: None,
            epoch: Some(0),
            finalized_at: Some(SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs()),
            title: payload.title.clone(),
            description: payload.description.clone(),
            icon_cid: payload.icon_cid.clone(),
            created_at: None,
            updated_at: Some(SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs() as i64),
        };
        let _ = state.swarm_tx.send(SwarmCommand::PublishDht(payload.name.clone(), res));

        return Json(NameRegisterRes { success: true, error: None });
    }

    Json(NameRegisterRes { success: false, error: Some("DID not found".into()) })
}

async fn get_names_by_did(State(state): State<AppState>, Path(did): Path<String>) -> Json<Vec<serde_json::Value>> {
    let name_db = state.name_db.lock().await;
    let mut results = Vec::new();
    if let Ok(records) = name_db.get_names_by_did(&did) {
        for record in records {
            results.push(serde_json::json!({
                "domain": record.name,
                "cid": record.cid,
                "title": record.title,
                "description": record.description,
                "icon_cid": record.icon_cid,
                "created_at": record.created_at,
                "updated_at": record.updated_at
            }));
        }
    }
    Json(results)
}

// --- Grant System Handlers ---

#[derive(Deserialize)]
struct CreateGrantRequest {
    grant_id: String,
    title: String,
    amount_per_claim: u64,
    max_claims: u64,            // 0 = без ліміту
    expires_at: u64,            // 0 = безстроково
    signer: String,             // wallet-адреса валідатора
    signature: String,          // ECDSA підпис повідомлення
}

#[derive(Serialize)]
struct CreateGrantResponse {
    success: bool,
    error: Option<String>,
}

#[derive(Deserialize)]
struct ClaimGrantRequest {
    grant_id: String,
    did: String,
}

#[derive(Serialize)]
struct ClaimGrantResponse {
    success: bool,
    amount: u64,
    new_balance: u64,
    error: Option<String>,
}

async fn create_grant(
    State(state): State<AppState>,
    Json(payload): Json<CreateGrantRequest>,
) -> Json<CreateGrantResponse> {
    use std::collections::HashSet;

    // 1. Побудувати повідомлення (саме те що підписав валідатор)
    let message = format!(
        "create_grant:{}:{}:{}:{}",
        payload.grant_id, payload.title, payload.amount_per_claim, payload.max_claims
    );

    // 2. Перевірити права через GrantAuthority (підпис + комітет)
    let ppor = state.ppor_manager.lock().await;
    let authorized = state.grant_authority.can_create_grant(
        &payload.signer,
        &message,
        &payload.signature,
        &ppor.current_committee,
    );
    drop(ppor);

    if !authorized {
        return Json(CreateGrantResponse {
            success: false,
            error: Some("Unauthorized: signature invalid or not a committee member".into()),
        });
    }

    // 3. Створити грант
    let grant = ppor::GrantProgram {
        grant_id: payload.grant_id.clone(),
        title: payload.title.clone(),
        signer: payload.signer.clone(),
        verification: ppor::GrantVerification::Open,
        amount_per_claim: payload.amount_per_claim,
        max_claims: payload.max_claims,
        claimed_count: 0,
        claimed_total: 0,
        claimed_by: HashSet::new(),
        created_at: SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs(),
        expires_at: payload.expires_at,
        active: true,
    };

    let (tx, rx) = tokio::sync::oneshot::channel();
    let _ = state.swarm_tx.send(SwarmCommand::CreateGrant { grant, response_tx: tx });

    match rx.await {
        Ok(Ok(())) => {
            eprintln!("[GRANT API] Created grant: {}", payload.grant_id);
            Json(CreateGrantResponse { success: true, error: None })
        }
        Ok(Err(e)) => Json(CreateGrantResponse { success: false, error: Some(e) }),
        Err(_) => Json(CreateGrantResponse { success: false, error: Some("Internal error".into()) }),
    }
}

async fn claim_grant(
    State(state): State<AppState>,
    Json(payload): Json<ClaimGrantRequest>,
) -> Json<ClaimGrantResponse> {
    let (tx, rx) = tokio::sync::oneshot::channel();
    let _ = state.swarm_tx.send(SwarmCommand::ClaimGrant {
        grant_id: payload.grant_id.clone(),
        did: payload.did.clone(),
        response_tx: tx,
    });

    match rx.await {
        Ok(Ok((amount, new_balance))) => Json(ClaimGrantResponse {
            success: true, amount, new_balance, error: None,
        }),
        Ok(Err(e)) => Json(ClaimGrantResponse {
            success: false, amount: 0, new_balance: 0, error: Some(e),
        }),
        Err(_) => Json(ClaimGrantResponse {
            success: false, amount: 0, new_balance: 0, error: Some("Internal error".into()),
        }),
    }
}

async fn get_grant_info(
    State(state): State<AppState>,
    Path(grant_id): Path<String>,
) -> Json<Option<swarm_loop::GrantInfoResponse>> {
    let (tx, rx) = tokio::sync::oneshot::channel();
    let _ = state.swarm_tx.send(SwarmCommand::GetGrantInfo { grant_id, response_tx: tx });
    Json(rx.await.ok().flatten())
}

async fn list_grants(
    State(state): State<AppState>,
) -> Json<Vec<swarm_loop::GrantInfoResponse>> {
    let (tx, rx) = tokio::sync::oneshot::channel();
    let _ = state.swarm_tx.send(SwarmCommand::ListGrants { response_tx: tx });
    Json(rx.await.unwrap_or_default())
}

#[derive(serde::Serialize)]
struct PeersResponse {
    consensus_nodes: Vec<String>,
    consensus_grpc: Vec<String>,
}

async fn handle_peers() -> axum::Json<PeersResponse> {
    let peer_cache = crate::peer_cache::PeerCache::load("peer_cache.json");
    let mut consensus_nodes = Vec::new();
    let mut consensus_grpc = Vec::new();
    for entry in peer_cache.peers.values() {
        if let Some(url) = &entry.api_url {
            consensus_nodes.push(url.clone());
        }
        if let Some(grpc) = &entry.grpc_url {
            consensus_grpc.push(grpc.clone());
        }
    }
    axum::Json(PeersResponse { consensus_nodes, consensus_grpc })
}

async fn handle_stats(
    axum::extract::State(state): axum::extract::State<AppState>,
) -> axum::Json<crate::telemetry::AggregatedStats> {
    let cache = state.telemetry_cache.lock().await;
    axum::Json(cache.aggregate())
}

fn load_keypair_from_env_or_file(keypair_path: &str) -> libp2p::identity::Keypair {
    if let Ok(hex_str) = std::env::var("NODE_PRIVATE_KEY") {
        if let Ok(bytes) = hex::decode(hex_str.trim()) {
            let mut key_bytes = bytes;
            if let Ok(secret_key) = libp2p::identity::ed25519::SecretKey::try_from_bytes(&mut key_bytes[..]) {
                let kp = libp2p::identity::ed25519::Keypair::from(secret_key);
                eprintln!("Loaded Peer Key from NODE_PRIVATE_KEY env var");
                return libp2p::identity::Keypair::from(kp);
            }
        }
        eprintln!("Failed to parse NODE_PRIVATE_KEY from env, falling back to file");
    }
    
    if let Ok(bytes) = std::fs::read(keypair_path) {
        libp2p::identity::Keypair::from_protobuf_encoding(&bytes).unwrap_or_else(|_| {
            eprintln!("Failed to decode peer_key.bin protobuf, generating a new key");
            let key = libp2p::identity::Keypair::generate_ed25519();
            if let Err(e) = std::fs::write(keypair_path, key.to_protobuf_encoding().unwrap()) {
                eprintln!("Failed to write generated peer_key.bin: {:?}", e);
            }
            key
        })
    } else {
        let key = libp2p::identity::Keypair::generate_ed25519();
        if let Err(e) = std::fs::write(keypair_path, key.to_protobuf_encoding().unwrap()) {
            eprintln!("Failed to write generated peer_key.bin: {:?}", e);
        }
        key
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let grpc_port: u16 = std::env::var("GRPC_PORT")
        .unwrap_or_else(|_| "50051".to_string())
        .parse()
        .unwrap_or(50051);
    let http_port: u16 = std::env::var("HTTP_PORT")
        .unwrap_or_else(|_| "3000".to_string())
        .parse()
        .unwrap_or(3000);
    let grpc_addr: SocketAddr = format!("0.0.0.0:{}", grpc_port).parse().unwrap();
    let http_addr: SocketAddr = format!("0.0.0.0:{}", http_port).parse().unwrap();

    let db_dir = std::env::var("DB_DIR").unwrap_or_else(|_| "consensus_db".to_string());
    std::fs::create_dir_all(&db_dir).unwrap_or_default();

    let sled_db = sled::open(format!("{}/sled", db_dir))?;
    let ledger = Arc::new(accounting::Ledger::new(sled_db.clone()));
    let did_manager = Arc::new(Mutex::new(did::DidManager::new(sled_db.clone())));
    
    let name_db = Arc::new(Mutex::new(name_db::NameDb::new(&format!("{}/names.db", db_dir)).unwrap()));
    let acl_manager = Arc::new(acl::AclManager::new(sled_db.clone()));

    let rpc_url = std::env::var("ETH_RPC_URL").unwrap_or_else(|_| "https://polygon-rpc.com".to_string());
    
    let eth_bridge = Arc::new(eth_bridge::Web3Bridge::new(&rpc_url, ledger.clone()).unwrap());
    let bridge_clone = eth_bridge.clone();
    tokio::spawn(async move {
        bridge_clone.start_event_listener().await;
    });

    let keypair_path = format!("{}/peer_key.bin", db_dir);
    let local_key = load_keypair_from_env_or_file(&keypair_path);
    let local_peer_id = PeerId::from(local_key.public());
    eprintln!("Consensus Local peer id: {:?}", local_peer_id);

    let node_wallet_address = std::env::var("NODE_WALLET_ADDRESS")
        .unwrap_or_else(|_| "0x0000000000000000000000000000000000000000".to_string())
        .to_lowercase();
    eprintln!("Node Wallet Address (committee identity): {}", node_wallet_address);

    let epoch_secs: u64 = std::env::var("EPOCH_DURATION_SECS")
        .unwrap_or_else(|_| "600".to_string())
        .parse()
        .unwrap_or(600);

    // Комітет більше не береться зі смарт-контракту.
    // Починаємо з self-only — select_committee_weighted() у ppor.rs
    // самостійно сформує комітет при першій ротації епохи на основі
    // репутації та активності відомих нод.
    let ppor_manager = Arc::new(Mutex::new(ppor::PporManager::new_with_committee_and_epoch(
        node_wallet_address.clone(),
        vec![node_wallet_address.clone()],
        Duration::from_secs(epoch_secs),
    )));

    let mut swarm = SwarmBuilder::with_existing_identity(local_key.clone())
        .with_tokio()
        .with_tcp(
            libp2p::tcp::Config::default(),
            libp2p::noise::Config::new,
            libp2p::yamux::Config::default,
        )?
        .with_quic()
        .with_behaviour(|key| {
            let gossipsub_config = gossipsub::ConfigBuilder::default()
                .heartbeat_interval(Duration::from_secs(1))
                .validation_mode(gossipsub::ValidationMode::Strict)
                .max_transmit_size(10 * 1024 * 1024)
                .build()
                .expect("Valid gossipsub config");
            
            let mut gossipsub = gossipsub::Behaviour::new(
                gossipsub::MessageAuthenticity::Signed(key.clone()),
                gossipsub_config,
            ).expect("Valid gossipsub behaviour");

            // Phase 1: CONDITIONAL subscription to feedo_consensus_ppor.
            // When CONSENSUS_DIRECT_MODE=true (default), PBFT goes via direct
            // request-response, but we still LISTEN on gossipsub for backward
            // compatibility with old nodes that haven't upgraded yet.
            let direct_mode = std::env::var("CONSENSUS_DIRECT_MODE")
                .unwrap_or_else(|_| "true".to_string()) == "true";

            // Always subscribe — needed for backward-compat receive.
            // SENDING behavior is controlled by the direct_mode flag in swarm_loop.rs.
            gossipsub.subscribe(&gossipsub::IdentTopic::new("feedo_consensus_ppor")).unwrap();
            gossipsub.subscribe(&gossipsub::IdentTopic::new("feedo_name_registrations")).unwrap();
            gossipsub.subscribe(&gossipsub::IdentTopic::new("feedo_did_updates")).unwrap();
            gossipsub.subscribe(&gossipsub::IdentTopic::new("feedo_name_txs")).unwrap();
            gossipsub.subscribe(&gossipsub::IdentTopic::new("feedo_update_cid_txs")).unwrap();
            gossipsub.subscribe(&gossipsub::IdentTopic::new("feedo_ledger_txs")).unwrap();
            gossipsub.subscribe(&gossipsub::IdentTopic::new("feedo_peer_announce")).unwrap();
            gossipsub.subscribe(&gossipsub::IdentTopic::new("feedo_update_metadata_txs")).unwrap();
            gossipsub.subscribe(&gossipsub::IdentTopic::new("feedo_telemetry")).unwrap();

            if direct_mode {
                eprintln!("[CONSENSUS] Phase 1 direct-mode: still listening on feedo_consensus_ppor for backward-compat, but will SEND via request-response");
            }

            let kad_config = libp2p::kad::Config::default();
            let db_dir = std::env::var("DB_DIR").unwrap_or_else(|_| "consensus_db".to_string());
            let store = dht_store::SledRecordStore::new(sled::open(format!("{}/kademlia_db", db_dir)).unwrap());
            let mut kademlia = libp2p::kad::Behaviour::with_config(local_peer_id, store, kad_config);
            kademlia.set_mode(Some(libp2p::kad::Mode::Server));

            let identify = libp2p::identify::Behaviour::new(libp2p::identify::Config::new(
                "/feedo-consensus/1.0.0".to_string(),
                key.public(),
            ));

            let mdns = libp2p::mdns::tokio::Behaviour::new(libp2p::mdns::Config::default(), local_peer_id).unwrap();

            // Phase 1: Use ConsensusCodec (supports both TxRelay and PbftVote)
            let rr_codec = ConsensusCodec;
            let rr_protocols = vec![
                (CONSENSUS_PROTOCOL.to_string(), libp2p::request_response::ProtocolSupport::Full)
            ];
            let rr_cfg = libp2p::request_response::Config::default();
            let rr = libp2p::request_response::Behaviour::with_codec(rr_codec, rr_protocols, rr_cfg);

            network::ConsensusBehaviour {
                gossipsub,
                kademlia,
                identify,
                mdns,
                request_response: rr,
            }
        })?
        .with_swarm_config(|c| c.with_idle_connection_timeout(Duration::from_secs(60)))
        .build();

    let p2p_port = std::env::var("P2P_PORT").unwrap_or_else(|_| "8041".to_string());
    swarm.listen_on(format!("/ip4/0.0.0.0/udp/{}/quic-v1", p2p_port).parse()?)?;

    if let Ok(nodes_csv) = std::env::var("BOOTSTRAP_NODES") {
        let mut bootstrapped = false;
        for s in nodes_csv.split(',') {
            let s = s.trim();
            if s.is_empty() { continue; }
            match s.parse::<libp2p::Multiaddr>() {
                Ok(addr) => {
                    if let Some(libp2p::multiaddr::Protocol::P2p(peer_id)) = addr.iter().find(|p| matches!(p, libp2p::multiaddr::Protocol::P2p(_))) {
                        swarm.behaviour_mut().kademlia.add_address(&peer_id, addr.clone());
                        bootstrapped = true;
                    }
                    match swarm.dial(addr.clone()) {
                        Ok(()) => eprintln!("Dialing bootstrap node: {}", addr),
                        Err(e) => eprintln!("Error dialing {}: {:?}", addr, e),
                    }
                }
                Err(e) => eprintln!("Invalid bootstrap multiaddr '{}': {:?}", s, e),
            }
        }
        if bootstrapped {
            let _ = swarm.behaviour_mut().kademlia.bootstrap();
            eprintln!("Initiated Kademlia bootstrap");
        }
    }

    let (swarm_tx, swarm_rx) = mpsc::unbounded_channel();
    let ppor_clone = ppor_manager.clone();
    let ppor_shutdown = ppor_manager.clone();
    let name_db_clone = name_db.clone();
    let did_manager_clone = did_manager.clone();
    let ledger_clone = ledger.clone();
    
    let telemetry_cache = Arc::new(Mutex::new(telemetry::TelemetryCache::new("telemetry_cache.json")));
    let telemetry_clone = telemetry_cache.clone();

    tokio::spawn(async move {
        crate::swarm_loop::run_swarm(swarm, swarm_rx, ppor_clone, name_db_clone, did_manager_clone, ledger_clone, telemetry_clone).await;
    });

    let consensus_service = MyConsensusService {
        ledger: ledger.clone(),
        did_manager: did_manager.clone(),
        eth_bridge,
        name_db: name_db.clone(),
        ppor_manager: ppor_manager.clone(),
        swarm_tx: swarm_tx.clone(),
        acl_manager: acl_manager.clone(),
    };

    eprintln!("Starting gRPC Consensus Service on {}", grpc_addr);
    let grpc_server = Server::builder()
        .add_service(ConsensusServiceServer::new(consensus_service))
        .serve(grpc_addr);

    let cors = tower_http::cors::CorsLayer::permissive();

    let grant_authority = Arc::new(authority::CommitteeGrantAuthority);


    let app_state = AppState {
        name_db: name_db.clone(),
        did_manager: did_manager.clone(),
        swarm_tx: swarm_tx.clone(),
        ledger: ledger.clone(),
        ppor_manager: ppor_manager.clone(),
        grant_authority,
        acl_manager: acl_manager.clone(),
        telemetry_cache: telemetry_cache.clone(),
    };
    
    let app = Router::new()
        .route("/resolve/:name", get(resolve_name_http))
        .route("/resolve_cid/:cid", get(resolve_cid_http))
        .route("/did/:did/balance", get(get_did_balance))
    .route("/did/:did/storage_usage", get(get_storage_usage_http))
    .route("/storage/reserve", post(reserve_storage_http))
    .route("/storage/release", post(release_storage_http))
        .route("/did/:did/names", get(get_names_by_did))
        .route("/did/register", post(register_did))
        .route("/name/register", post(register_name))
        .route("/name/update_cid", post(update_cid))
        .route("/name/update_metadata", post(update_metadata))
        .route("/grant/create", post(create_grant))
        .route("/grant/claim", post(claim_grant))
        .route("/grant/access", post(grant_file_access))
        .route("/grant/access/:file_hash/:grantee_did", get(get_file_access))
        .route("/grant/:grant_id", get(get_grant_info))
        .route("/grants", get(list_grants))
        .route("/api/v1/peers", get(handle_peers))
        .route("/api/v1/stats", get(handle_stats))
        .layer(cors)
        .with_state(app_state);
    let listener = tokio::net::TcpListener::bind(http_addr).await.unwrap();
    eprintln!("Starting HTTP server on {}", http_addr);
    let http_server = axum::serve(listener, app);

    let shutdown_swarm_tx = swarm_tx.clone();
    let shutdown_ppor = ppor_shutdown;
    let shutdown_handle = tokio::spawn(async move {
        tokio::signal::ctrl_c().await.ok();
        eprintln!("[SHUTDOWN] Received SIGINT, initiating graceful shutdown...");

        let manager = shutdown_ppor.lock().await;
        let my_wallet = manager.node_id.clone();
        let my_reputation = manager.reputation_table.get(&my_wallet).copied().unwrap_or(10);
        drop(manager);
        let _ = shutdown_swarm_tx.send(SwarmCommand::PublishReputationDht(my_wallet, my_reputation));

        tokio::time::sleep(Duration::from_secs(2)).await;

        eprintln!("[SHUTDOWN] Graceful shutdown complete");
        std::process::exit(0);
    });

    tokio::select! {
        _ = grpc_server => eprintln!("gRPC server exited"),
        _ = http_server => eprintln!("HTTP server exited"),
        _ = shutdown_handle => {},
    }

    Ok(())
}