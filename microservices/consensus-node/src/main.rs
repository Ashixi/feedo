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
pub mod pbft;
pub mod network;
pub mod swarm_loop;

use swarm_loop::SwarmCommand;

pub struct MyConsensusService {
    ledger: Arc<accounting::Ledger>,
    did_manager: Arc<Mutex<did::DidManager>>,
    eth_bridge: Arc<eth_bridge::Web3Bridge>,
    name_db: Arc<Mutex<name_db::NameDb>>,
    pbft_manager: Arc<Mutex<pbft::PbftManager>>,
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
        
        let did_manager = self.did_manager.lock().await;
        if let Some(doc) = did_manager.get_document(&req.user_did) {
            if doc.feedo_state.balance_credits > 0 {
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
        if let Ok(Some((_, Some(hash)))) = name_db.resolve_name(&req.name) {
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
}

#[derive(Serialize, Deserialize, Clone)]
pub struct ResolveRes {
    pub did: String,
    pub cid: Option<String>,
}

async fn register_did(State(state): State<AppState>, Json(payload): Json<DidRegisterReq>) -> Json<DidRegisterRes> {
    let ts = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
    let did_id = format!("did:feedo:{}", payload.public_key.trim_start_matches("0x"));
    let doc = did::DidDocument::new(did_id.clone(), payload.public_key.clone(), ts);
    let did_manager = state.did_manager.lock().await;
    let _ = did_manager.insert_document(&doc);
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

    let did_manager = state.did_manager.lock().await;
    let doc = did_manager.get_document(&payload.did);
    if let Some(mut doc) = doc {
        if doc.feedo_state.balance_credits < 100 {
            return Json(NameRegisterRes { success: false, error: Some("Insufficient credits".into()) });
        }
        doc.feedo_state.balance_credits -= 100;
        let _ = did_manager.insert_document(&doc);
    } else {
        return Json(NameRegisterRes { success: false, error: Some("DID not found".into()) });
    }

    let _ = name_db.insert_name(&payload.name, &payload.did, &payload.public_key);
    
    // Publish to DHT
    let res = ResolveRes { did: payload.did.clone(), cid: None };
    let _ = state.swarm_tx.send(SwarmCommand::PublishDht(payload.name.clone(), res));
    
    Json(NameRegisterRes { success: true, error: None })
}

async fn update_cid(State(state): State<AppState>, Json(payload): Json<UpdateCidReq>) -> Json<NameRegisterRes> {
    let name_db = state.name_db.lock().await;
    let resolved = name_db.resolve_name(&payload.name).unwrap_or(None);
    if let Some((did_id, _)) = resolved {
        let did_manager = state.did_manager.lock().await;
        if let Some(doc) = did_manager.get_document(&did_id) {
            let pub_key = &doc.verification_method[0].public_key_multibase;
            let payload_bytes = format!("{}{}", payload.name, payload.cid).into_bytes();
            if !did::verify_signature(pub_key, &payload_bytes, &payload.signature) {
                return Json(NameRegisterRes { success: false, error: Some("Invalid signature".into()) });
            }
            let _ = name_db.update_cid(&payload.name, &payload.cid);
            
            // Publish to DHT
            let res = ResolveRes { did: did_id, cid: Some(payload.cid.clone()) };
            let _ = state.swarm_tx.send(SwarmCommand::PublishDht(payload.name.clone(), res));
            
            return Json(NameRegisterRes { success: true, error: None });
        }
    }
    Json(NameRegisterRes { success: false, error: Some("Name not found or DID missing".into()) })
}

async fn resolve_name_http(State(state): State<AppState>, Path(name): Path<String>) -> Json<Option<ResolveRes>> {
    let name_db = state.name_db.lock().await;
    if let Ok(Some((did, cid))) = name_db.resolve_name(&name) {
        return Json(Some(ResolveRes { did, cid }));
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
    
    let pbft_manager = Arc::new(Mutex::new(pbft::PbftManager::new("node_id_placeholder".to_string())));

    let local_key = identity::Keypair::generate_ed25519();
    let local_peer_id = PeerId::from(local_key.public());
    println!("Consensus Local peer id: {:?}", local_peer_id);

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

            gossipsub.subscribe(&gossipsub::IdentTopic::new("feedo_consensus_pbft")).unwrap();
            gossipsub.subscribe(&gossipsub::IdentTopic::new("feedo_name_registrations")).unwrap();
            gossipsub.subscribe(&gossipsub::IdentTopic::new("feedo_did_updates")).unwrap();

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
    let pbft_clone = pbft_manager.clone();
    let name_clone = name_db.clone();
    
    tokio::spawn(async move {
        crate::swarm_loop::run_swarm(swarm, swarm_rx, pbft_clone, name_clone).await;
    });

    let consensus_service = MyConsensusService {
        ledger,
        did_manager: did_manager.clone(),
        eth_bridge,
        name_db: name_db.clone(),
        pbft_manager,
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
    };
    
    // Republish local records to DHT on startup
    let local_name_db = name_db.lock().await;
    if let Ok(records) = local_name_db.get_all_records() {
        for (name, did, cid) in records {
            let res = ResolveRes { did, cid };
            let _ = swarm_tx.send(SwarmCommand::PublishDht(name, res));
        }
    }
    drop(local_name_db);
    
    let app = Router::new()
        .route("/resolve/:name", get(resolve_name_http))
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
