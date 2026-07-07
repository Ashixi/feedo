use axum::{routing::{get, post}, Router, Json, extract::{State, Path}};
use serde::{Deserialize, Serialize};
use std::time::{SystemTime, UNIX_EPOCH};
use shared_proto::consensus::consensus_service_server::{ConsensusService, ConsensusServiceServer};
use shared_proto::consensus::{
    Empty, MissingChunkRequest, MissingChunkResponse, ResolveNameRequest,
    ResolveNameResponse, ValidatorList, VerifyUploadRequest, VerifyUploadResponse,
};
use tonic::{transport::Server, Request, Response, Status};
use std::net::SocketAddr;

use std::sync::Arc;
use tokio::sync::Mutex;
use libp2p::{SwarmBuilder, PeerId, identity, gossipsub};
use std::time::Duration;
use tokio::sync::mpsc;

pub mod accounting;
pub mod did;
pub mod eth_bridge;
pub mod name_db;
pub mod ppor;
pub mod network;
pub mod swarm_loop;

use swarm_loop::SwarmCommand;

pub struct MyConsensusService {
    ledger: Arc<accounting::Ledger>,
    did_manager: Arc<Mutex<did::DidManager>>,
    eth_bridge: Arc<eth_bridge::Web3Bridge>,
    name_db: Arc<Mutex<name_db::NameDb>>,
    ppor_manager: Arc<Mutex<ppor::PporManager>>,
    swarm_tx: mpsc::UnboundedSender<SwarmCommand>,
}

#[tonic::async_trait]
impl ConsensusService for MyConsensusService {
    async fn verify_upload_rights(
        &self,
        request: Request<VerifyUploadRequest>,
    ) -> Result<Response<VerifyUploadResponse>, Status> {
        let req = request.into_inner();
        println!("VerifyUploadRequest: did={}, hash={}", req.user_did, req.file_hash);
        
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
}

#[derive(Deserialize)]
pub struct DidRegisterReq { pub public_key: String }

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
    pub signature: String, // Can be empty for system-issued credits like initial balance
}
impl LedgerTx {
    pub fn tx_hash(&self) -> String {
        use sha2::{Sha256, Digest};
        let mut hasher = Sha256::new();
        hasher.update(format!("{}{}{}{}", self.did, self.amount, self.is_credit, self.signature));
        hex::encode(hasher.finalize())
    }
}

#[derive(Serialize, Deserialize, Clone)]
pub struct ResolveRes {
    pub did: String,
    pub cid: Option<String>,
    pub gateways: Option<Vec<String>>,
}

async fn register_did(State(state): State<AppState>, Json(payload): Json<DidRegisterReq>) -> Json<DidRegisterRes> {
    let ts = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
    let did_id = format!("did:feedo:{}", payload.public_key.trim_start_matches("0x"));
    let doc = did::DidDocument::new(did_id.clone(), payload.public_key.clone(), ts);
    let did_manager = state.did_manager.lock().await;
    let _ = did_manager.insert_document(&doc);
    drop(did_manager);

    // Provide 500000 initial credits via PPoS LedgerTx instead of local credit
    let tx = LedgerTx {
        did: did_id.clone(),
        amount: 500000,
        is_credit: true,
        signature: "SYSTEM".to_string(), // Initial registration bonus is system-authorized
    };
    let _ = state.swarm_tx.send(SwarmCommand::BroadcastLedgerTx(tx));

    let _ = state.swarm_tx.send(SwarmCommand::PublishDidDht(did_id.clone(), doc));
    Json(DidRegisterRes { did: did_id })
}

async fn register_name(State(state): State<AppState>, Json(payload): Json<NameRegisterReq>) -> Json<NameRegisterRes> {
    let payload_bytes = format!("{}{}", payload.name, payload.did).into_bytes();
    if !did::verify_signature(&payload.public_key, &payload_bytes, &payload.signature) {
        return Json(NameRegisterRes { success: false, error: Some("Invalid signature".into()) });
    }

    let name_db = state.name_db.lock().await;
    if name_db.name_exists(&payload.name).unwrap_or(false) {
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
                // Cache it locally
                let did_manager = state.did_manager.lock().await;
                let _ = did_manager.insert_document(&doc);
                resolved_doc = Some(doc);
            }
        }
    }

    if let Some(doc) = resolved_doc {
        let local_ledger_balance = state.ledger.get_balance(&payload.did).await;
        if local_ledger_balance < 100 {
            return Json(NameRegisterRes { success: false, error: Some("Insufficient credits".into()) });
        }

        let tx = NameRegistrationTx {
            name: payload.name,
            did: payload.did,
            public_key: payload.public_key,
            signature: payload.signature,
        };
        
        // Broadcast via Swarm
        let _ = state.swarm_tx.send(SwarmCommand::BroadcastNameTx(tx));
        
        return Json(NameRegisterRes { success: true, error: None });
    }

    Json(NameRegisterRes { success: false, error: Some("DID not found".into()) })
}

async fn update_cid(State(state): State<AppState>, Json(payload): Json<UpdateCidReq>) -> Json<NameRegisterRes> {
    // 1. Resolve name (local or DHT fallback)
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
                // Cache it locally
                let name_db = state.name_db.lock().await;
                let gateways_json = res.gateways.as_ref().map(|g| serde_json::to_string(g).unwrap_or_else(|_| "[]".to_string()));
                let _ = name_db.insert_name(&payload.name, &res.did, ""); // empty pubkey for cache
                if let Some(cid) = &res.cid {
                    let _ = name_db.update_cid(&payload.name, cid, &gateways_json.unwrap_or_else(|| "[]".to_string()));
                }
                drop(name_db);
                resolved_did_id = Some(res.did);
            }
        }
    }
    
    if let Some(did_id) = resolved_did_id {
        // 2. Resolve DID (local or DHT fallback)
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
                    // Cache it locally
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
                name: payload.name,
                cid: payload.cid,
                signature: payload.signature,
                gateways: payload.gateways,
            };
            
            // Broadcast via Swarm
            let _ = state.swarm_tx.send(SwarmCommand::BroadcastUpdateCidTx(tx));
            
            return Json(NameRegisterRes { success: true, error: None });
        }
    }
    Json(NameRegisterRes { success: false, error: Some("Name not found or DID missing".into()) })
}

async fn resolve_name_http(State(state): State<AppState>, Path(name): Path<String>) -> Json<Option<ResolveRes>> {
    let name_db = state.name_db.lock().await;
    if let Ok(Some((did, cid, gateways_json))) = name_db.resolve_name(&name) {
        let gateways = gateways_json.and_then(|json| serde_json::from_str(&json).ok());
        return Json(Some(ResolveRes { did, cid, gateways }));
    }
    drop(name_db);

    // Fallback to Kademlia DHT
    let (tx, rx) = tokio::sync::oneshot::channel();
    if state.swarm_tx.send(SwarmCommand::LookupDht(name.clone(), tx)).is_ok() {
        if let Ok(Some(res)) = rx.await {
            return Json(Some(res));
        }
    }
    
    Json(None)
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
    let balance = state.ledger.get_balance(&did).await;
    // We assume if balance > 0 or if DID exists, we return it.
    // To strictly match Optional return if DID doesn't exist:
    let did_manager = state.did_manager.lock().await;
    if did_manager.get_document(&did).is_none() && balance == 0 {
        return Json(None);
    }
    drop(did_manager);

    Json(Some(BalanceRes {
        balance_credits: balance,
    }))
}

async fn get_names_by_did(State(state): State<AppState>, Path(did): Path<String>) -> Json<Vec<serde_json::Value>> {
    let name_db = state.name_db.lock().await;
    let mut results = Vec::new();
    if let Ok(records) = name_db.get_names_by_did(&did) {
        for (name, cid) in records {
            results.push(serde_json::json!({
                "domain": name,
                "cid": cid
            }));
        }
    }
    Json(results)
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let grpc_addr: SocketAddr = "0.0.0.0:50051".parse().unwrap();
    let http_addr: SocketAddr = "0.0.0.0:3000".parse().unwrap();

    let sled_db = sled::open("consensus_db")?;
    let ledger = Arc::new(accounting::Ledger::new(sled_db.clone()));
    let did_manager = Arc::new(Mutex::new(did::DidManager::new(sled_db.clone())));
    
    let name_db = Arc::new(Mutex::new(name_db::NameDb::new("names.db").unwrap()));

    let rpc_url = std::env::var("ETH_RPC_URL").unwrap_or_else(|_| "https://polygon-rpc.com".to_string());
    
    let eth_bridge = Arc::new(eth_bridge::Web3Bridge::new(&rpc_url, ledger.clone()).unwrap());
    let bridge_clone = eth_bridge.clone();
    tokio::spawn(async move {
        bridge_clone.start_event_listener().await;
    });
    
fn load_keypair_from_env_or_file(keypair_path: &str) -> libp2p::identity::Keypair {
    if let Ok(hex_str) = std::env::var("NODE_PRIVATE_KEY") {
        if let Ok(bytes) = hex::decode(hex_str.trim()) {
            let mut key_bytes = bytes;
            if let Ok(secret_key) = libp2p::identity::ed25519::SecretKey::try_from_bytes(&mut key_bytes) {
                let kp = libp2p::identity::ed25519::Keypair::from(secret_key);
                println!("Loaded Peer Key from NODE_PRIVATE_KEY env var");
                return libp2p::identity::Keypair::from(kp);
            }
        }
        println!("Failed to parse NODE_PRIVATE_KEY from env, falling back to file");
    }
    
    if let Ok(bytes) = std::fs::read(keypair_path) {
        libp2p::identity::Keypair::from_protobuf_encoding(&bytes).unwrap_or_else(|_| {
            println!("Failed to decode peer_key.bin protobuf, generating a new key");
            let key = libp2p::identity::Keypair::generate_ed25519();
            if let Err(e) = std::fs::write(keypair_path, key.to_protobuf_encoding().unwrap()) {
                println!("Failed to write generated peer_key.bin: {:?}", e);
            }
            key
        })
    } else {
        let key = libp2p::identity::Keypair::generate_ed25519();
        if let Err(e) = std::fs::write(keypair_path, key.to_protobuf_encoding().unwrap()) {
            println!("Failed to write generated peer_key.bin: {:?}", e);
        }
        key
    }
}

    let keypair_path = "consensus_db/peer_key.bin";
    std::fs::create_dir_all("consensus_db").unwrap_or_default();
    let local_key = load_keypair_from_env_or_file(keypair_path);
    let local_peer_id = PeerId::from(local_key.public());
    println!("Consensus Local peer id: {:?}", local_peer_id);

    // Читаємо адресу цієї ноди з env
    let node_wallet_address = std::env::var("NODE_WALLET_ADDRESS")
        .unwrap_or_else(|_| "0x0000000000000000000000000000000000000000".to_string())
        .to_lowercase();
    println!("Node Wallet Address (committee identity): {}", node_wallet_address);

    // Отримуємо поточний комітет зі смартконтракту
    let on_chain_committee = eth_bridge.fetch_committee().await;

    let ppor_manager = Arc::new(Mutex::new(ppor::PporManager::new_with_committee(
        node_wallet_address.clone(),
        on_chain_committee,
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

            gossipsub.subscribe(&gossipsub::IdentTopic::new("feedo_consensus_ppor")).unwrap();
            gossipsub.subscribe(&gossipsub::IdentTopic::new("feedo_name_registrations")).unwrap();
            gossipsub.subscribe(&gossipsub::IdentTopic::new("feedo_did_updates")).unwrap();
            gossipsub.subscribe(&gossipsub::IdentTopic::new("feedo_name_txs")).unwrap();
            gossipsub.subscribe(&gossipsub::IdentTopic::new("feedo_update_cid_txs")).unwrap();
            gossipsub.subscribe(&gossipsub::IdentTopic::new("feedo_ledger_txs")).unwrap();

            let kad_config = libp2p::kad::Config::default();
            let store = libp2p::kad::store::MemoryStore::new(local_peer_id);
            let mut kademlia = libp2p::kad::Behaviour::with_config(local_peer_id, store, kad_config);
            kademlia.set_mode(Some(libp2p::kad::Mode::Server));

            let identify = libp2p::identify::Behaviour::new(libp2p::identify::Config::new(
                "/feedo-consensus/1.0.0".to_string(),
                key.public(),
            ));

            let mdns = libp2p::mdns::tokio::Behaviour::new(libp2p::mdns::Config::default(), local_peer_id).unwrap();

            network::ConsensusBehaviour {
                gossipsub,
                kademlia,
                identify,
                mdns,
            }
        })?
        .with_swarm_config(|c| c.with_idle_connection_timeout(Duration::from_secs(60)))
        .build();

    let p2p_port = std::env::var("P2P_PORT").unwrap_or_else(|_| "8041".to_string());
    swarm.listen_on(format!("/ip4/0.0.0.0/udp/{}/quic-v1", p2p_port).parse()?)?;

    if let Ok(nodes_csv) = std::env::var("BOOTSTRAP_NODES") {
        for s in nodes_csv.split(',') {
            let s = s.trim();
            if s.is_empty() { continue; }
            match s.parse::<libp2p::Multiaddr>() {
                Ok(addr) => {
                    match swarm.dial(addr.clone()) {
                        Ok(()) => println!("Dialing bootstrap node: {}", addr),
                        Err(e) => println!("Error dialing {}: {:?}", addr, e),
                    }
                }
                Err(e) => println!("Invalid bootstrap multiaddr '{}': {:?}", s, e),
            }
        }
    }

    let (swarm_tx, swarm_rx) = mpsc::unbounded_channel();
    let ppor_clone = ppor_manager.clone();
    let name_db_clone = name_db.clone();
    let did_manager_clone = did_manager.clone();
    let ledger_clone = ledger.clone();
    
    tokio::spawn(async move {
        crate::swarm_loop::run_swarm(swarm, swarm_rx, ppor_clone, name_db_clone, did_manager_clone, ledger_clone).await;
    });

    let consensus_service = MyConsensusService {
        ledger: ledger.clone(),
        did_manager: did_manager.clone(),
        eth_bridge,
        name_db: name_db.clone(),
        ppor_manager,
        swarm_tx: swarm_tx.clone(),
    };

    println!("Starting gRPC Consensus Service on {}", grpc_addr);
    let grpc_server = Server::builder()
        .add_service(ConsensusServiceServer::new(consensus_service))
        .serve(grpc_addr);

    let cors = tower_http::cors::CorsLayer::permissive();
    let app_state = AppState {
        name_db: name_db.clone(),
        did_manager: did_manager.clone(),
        swarm_tx: swarm_tx.clone(),
        ledger: ledger.clone(),
    };
    
    // Republish local records to DHT on startup
    let local_name_db = name_db.lock().await;
    if let Ok(records) = local_name_db.get_all_records() {
        for (name, did, cid, gateways_json) in records {
            let gateways = gateways_json.and_then(|json| serde_json::from_str(&json).ok());
            let res = ResolveRes { did, cid, gateways };
            let _ = swarm_tx.send(SwarmCommand::PublishDht(name, res));
        }
    }
    drop(local_name_db);
    
    let app = Router::new()
        .route("/resolve/:name", get(resolve_name_http))
        .route("/resolve_cid/:cid", get(resolve_cid_http))
        .route("/did/:did/balance", get(get_did_balance))
        .route("/did/:did/names", get(get_names_by_did))
        .route("/did/register", post(register_did))
        .route("/name/register", post(register_name))
        .route("/name/update_cid", post(update_cid))
        .layer(cors)
        .with_state(app_state);
    let listener = tokio::net::TcpListener::bind(http_addr).await.unwrap();
    println!("Starting HTTP server on {}", http_addr);
    let http_server = axum::serve(listener, app);

    tokio::select! {
        _ = grpc_server => println!("gRPC server exited"),
        _ = http_server => println!("HTTP server exited"),
    }

    Ok(())
}
