use axum::{routing::{get, post, delete}, Router, extract::{State, Multipart, Path, ws::{WebSocketUpgrade, WebSocket, Message as WsMessage}}};
use shared_proto::storage::storage_service_server::{StorageService, StorageServiceServer};
use shared_proto::storage::{ChunkData, Empty, FetchRequest, NewFileEvent};
use tonic::{transport::Server, Request, Response, Status};
use std::net::SocketAddr;
use tokio_stream::wrappers::ReceiverStream;
use tokio::sync::{mpsc, oneshot};
use libp2p::{
    SwarmBuilder, PeerId, identity, StreamProtocol,
    gossipsub, kad, identify, mdns, request_response,
};
use libp2p::gossipsub::{MessageAuthenticity, ValidationMode};
use std::sync::atomic::AtomicBool;
use std::sync::Arc;
use std::time::Duration;

mod network;
mod swarm_loop;
mod peer_cache;
mod quota;
mod telemetry;
mod auth;

use network::{StorageBehaviour, HybridStore, DirectRequest, DirectResponse};
use swarm_loop::{SwarmCommand, run_swarm};
use quota::{StorageClass, StorageQuotaManager, QuotaConfig};

#[derive(Clone)]
pub struct AppState {
    pub swarm_tx: mpsc::UnboundedSender<SwarmCommand>,
    pub recent_hashes: Arc<std::sync::Mutex<Vec<String>>>,
    pub gossip_tx: tokio::sync::broadcast::Sender<(String, Vec<u8>)>,
    pub quota_manager: Arc<StorageQuotaManager>,
}

pub struct MyStorageService {
    pub swarm_tx: mpsc::UnboundedSender<SwarmCommand>,
}

#[tonic::async_trait]
impl StorageService for MyStorageService {
    type InternalFetchFileStream = ReceiverStream<Result<ChunkData, Status>>;
    type StreamNewUploadsStream = ReceiverStream<Result<NewFileEvent, Status>>;

    async fn internal_fetch_file(
        &self,
        request: Request<FetchRequest>,
    ) -> Result<Response<Self::InternalFetchFileStream>, Status> {
        let req = request.into_inner();
        let (tx, rx) = tokio::sync::mpsc::channel(4);
        let (resp_tx, resp_rx) = oneshot::channel();
        
        let _ = self.swarm_tx.send(SwarmCommand::DhtDownload(req.file_hash, resp_tx));
        
        tokio::spawn(async move {
            match resp_rx.await {
                Ok(Some(data)) => {
                    let _ = tx.send(Ok(ChunkData { data })).await;
                }
                _ => {
                    let _ = tx.send(Err(Status::not_found("File not found"))).await;
                }
            }
        });
        
        Ok(Response::new(ReceiverStream::new(rx)))
    }

    async fn stream_new_uploads(
        &self,
        _request: Request<Empty>,
    ) -> Result<Response<Self::StreamNewUploadsStream>, Status> {
        let (_tx, rx) = mpsc::channel(4);
        
        Ok(Response::new(ReceiverStream::new(rx)))
    }
}

/// Extract StorageClass from HTTP header `X-Feedo-Storage-Class`.
/// Falls back to Blob if header is missing or invalid.
fn extract_storage_class_from_header(headers: &axum::http::HeaderMap) -> StorageClass {
    headers
        .get("X-Feedo-Storage-Class")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.parse::<StorageClass>().ok())
        .unwrap_or_default()
}

async fn handle_upload(
    _auth: auth::FeedoAuth,
    State(state): State<AppState>,
    headers: axum::http::HeaderMap,
    mut multipart: Multipart,
) -> Result<String, (axum::http::StatusCode, String)> {
    let storage_class = extract_storage_class_from_header(&headers);

    let mut file_data = Vec::new();
    while let Some(field) = multipart.next_field().await.map_err(|e| (axum::http::StatusCode::BAD_REQUEST, e.to_string()))? {
        if field.name() == Some("file") {
            let data = field.bytes().await.map_err(|e| (axum::http::StatusCode::BAD_REQUEST, e.to_string()))?;
            file_data.extend_from_slice(&data);
        }
    }
    
    if file_data.is_empty() {
        return Err((axum::http::StatusCode::BAD_REQUEST, "No file provided".to_string()));
    }

    // Check quota before sending to swarm
    if let Err(msg) = state.quota_manager.check_and_reserve(storage_class, file_data.len() as u64) {
        return Err((axum::http::StatusCode::INSUFFICIENT_STORAGE, msg));
    }

    let (resp_tx, resp_rx) = oneshot::channel();
    let _ = state.swarm_tx.send(SwarmCommand::DhtUpload(file_data, storage_class, resp_tx));
    
    match resp_rx.await {
        Ok(hash) => {
            state.recent_hashes.lock().unwrap().push(hash.clone());
            Ok(hash)
        },
        Err(_) => Err((axum::http::StatusCode::INTERNAL_SERVER_ERROR, "DHT upload failed".to_string())),
    }
}

#[derive(serde::Deserialize, serde::Serialize)]
pub struct IngestPayload {
    pub hash_id: String,
    pub author: String,
    pub text: String,
    pub target_hash: Option<String>,
    pub signature: String,
    pub metadata: serde_json::Value,
    pub ttl_days: Option<u32>,
    #[serde(default)]
    pub storage_class: Option<String>,
}

async fn handle_json_ingest(
    _auth: auth::FeedoAuth,
    State(state): State<AppState>,
    axum::Json(payload): axum::Json<IngestPayload>,
) -> Result<String, (axum::http::StatusCode, String)> {
    let storage_class: StorageClass = payload
        .storage_class
        .as_deref()
        .and_then(|s| s.parse().ok())
        .unwrap_or(StorageClass::SocialPost);

    let file_data = serde_json::to_vec(&payload).map_err(|e| (axum::http::StatusCode::BAD_REQUEST, e.to_string()))?;

    if let Err(msg) = state.quota_manager.check_and_reserve(storage_class, file_data.len() as u64) {
        return Err((axum::http::StatusCode::INSUFFICIENT_STORAGE, msg));
    }

    let (resp_tx, resp_rx) = oneshot::channel();
    let _ = state.swarm_tx.send(SwarmCommand::DhtUpload(file_data, storage_class, resp_tx));
    
    match resp_rx.await {
        Ok(hash) => {
            state.recent_hashes.lock().unwrap().push(hash.clone());
            Ok(hash)
        },
        Err(_) => Err((axum::http::StatusCode::INTERNAL_SERVER_ERROR, "DHT upload failed".to_string())),
    }
}

async fn handle_batch_json_ingest(
    _auth: auth::FeedoAuth,
    State(state): State<AppState>,
    axum::Json(payloads): axum::Json<Vec<IngestPayload>>,
) -> Result<axum::Json<Vec<String>>, (axum::http::StatusCode, String)> {
    let mut hashes = Vec::new();
    for payload in payloads {
        let storage_class: StorageClass = payload
            .storage_class
            .as_deref()
            .and_then(|s| s.parse().ok())
            .unwrap_or(StorageClass::Profile);

        let file_data = match serde_json::to_vec(&payload) {
            Ok(data) => data,
            Err(_) => continue,
        };

        if let Err(_msg) = state.quota_manager.check_and_reserve(storage_class, file_data.len() as u64) {
            continue; // skip this item, backpressure for class
        }

        let (resp_tx, resp_rx) = oneshot::channel();
        let _ = state.swarm_tx.send(SwarmCommand::DhtUpload(file_data, storage_class, resp_tx));
        if let Ok(hash) = resp_rx.await {
            state.recent_hashes.lock().unwrap().push(hash.clone());
            hashes.push(hash);
        }
    }
    Ok(axum::Json(hashes))
}

async fn handle_quota(
    _auth: auth::FeedoAuth,
    State(state): State<AppState>,
) -> axum::Json<serde_json::Value> {
    axum::Json(state.quota_manager.usage_all())
}

#[derive(serde::Serialize)]
struct PeersResponse {
    storage_nodes: Vec<String>,
}

async fn handle_peers() -> axum::Json<PeersResponse> {
    let peer_cache = crate::peer_cache::PeerCache::load("peer_cache.json");
    let mut storage_nodes = Vec::new();
    for entry in peer_cache.peers.values() {
        if let Some(url) = &entry.api_url {
            storage_nodes.push(url.clone());
        }
    }
    axum::Json(PeersResponse { storage_nodes })
}

async fn handle_recent_files(
    _auth: auth::FeedoAuth,
    State(state): State<AppState>,
) -> axum::Json<serde_json::Value> {
    let hashes = state.recent_hashes.lock().unwrap().clone();
    axum::Json(serde_json::json!({ "hashes": hashes }))
}

async fn handle_download(
    State(state): State<AppState>,
    Path(hash): Path<String>,
) -> Result<Vec<u8>, (axum::http::StatusCode, String)> {
    let (resp_tx, resp_rx) = oneshot::channel();
    let _ = state.swarm_tx.send(SwarmCommand::DhtDownload(hash, resp_tx));
    match resp_rx.await {
        Ok(Some(data)) => Ok(data),
        _ => Err((axum::http::StatusCode::NOT_FOUND, "Not found in DHT".to_string())),
    }
}

async fn handle_delete(
    _auth: auth::FeedoAuth,
    State(state): State<AppState>,
    Path(hash): Path<String>,
) -> Result<String, (axum::http::StatusCode, String)> {
    let _ = state.swarm_tx.send(SwarmCommand::DhtDelete(hash.clone()));
    state.recent_hashes.lock().unwrap().retain(|h| h != &hash);
    Ok("Deleted locally".to_string())
}

#[derive(serde::Deserialize)]
pub struct PublishPayload {
    pub topic: String,
    pub data: serde_json::Value,
}

async fn handle_publish(
    _auth: auth::FeedoAuth,
    State(state): State<AppState>,
    axum::Json(payload): axum::Json<PublishPayload>,
) -> Result<String, (axum::http::StatusCode, String)> {
    let data_bytes = if payload.data.is_string() {
        payload.data.as_str().unwrap().as_bytes().to_vec()
    } else {
        serde_json::to_vec(&payload.data).unwrap_or_default()
    };
    
    let _ = state.swarm_tx.send(SwarmCommand::Publish(payload.topic, data_bytes));
    Ok("Published".to_string())
}

async fn handle_subscribe(
    _auth: auth::FeedoAuth,
    ws: WebSocketUpgrade,
    Path(topic): Path<String>,
    State(state): State<AppState>,
) -> axum::response::Response {
    let _ = state.swarm_tx.send(SwarmCommand::SubscribeTopic(topic.clone()));
    
    let rx = state.gossip_tx.subscribe();
    ws.on_upgrade(move |socket| handle_ws(socket, topic, rx))
}

async fn handle_ws(mut socket: WebSocket, topic: String, mut rx: tokio::sync::broadcast::Receiver<(String, Vec<u8>)>) {
    while let Ok((msg_topic, data)) = rx.recv().await {
        if msg_topic == topic {
            if socket.send(WsMessage::Binary(data)).await.is_err() {
                break;
            }
        }
    }
}

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

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let db_dir = std::env::var("DB_DIR").unwrap_or_else(|_| "storage_db".to_string());
    let keypair_path = format!("{}/peer_key.bin", db_dir);
    std::fs::create_dir_all(&db_dir).unwrap_or_default();
    let local_key = load_keypair_from_env_or_file(&keypair_path);
    let local_peer_id = PeerId::from(local_key.public());
    println!("Local peer id: {:?}", local_peer_id);

    let db = sled::open(&db_dir).unwrap();

    // Phase 1: Replace hard-coded 10 GB global limit with per-class StorageQuotaManager
    let quota_config = QuotaConfig::from_env();
    let quota_manager = Arc::new(StorageQuotaManager::new(quota_config));

    // HybridStore no longer enforces global storage_full; quotas are checked higher in the stack.
    let storage_full = Arc::new(AtomicBool::new(false));
    let store = HybridStore::new(local_peer_id, db, storage_full.clone());

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

            let storage_topic = gossipsub::IdentTopic::new("storage_announcements");
            gossipsub.subscribe(&storage_topic).unwrap();
            let telemetry_topic = gossipsub::IdentTopic::new("feedo_telemetry");
            gossipsub.subscribe(&telemetry_topic).unwrap();

            let mut kad_config = libp2p::kad::Config::default();
            kad_config.set_query_timeout(Duration::from_secs(10));
            let mut kademlia = libp2p::kad::Behaviour::with_config(local_peer_id, store, kad_config);
            kademlia.set_mode(Some(libp2p::kad::Mode::Server));

            let identify = identify::Behaviour::new(identify::Config::new(
                "/feedo/1.0.0".to_string(),
                key.public(),
            ));

            let mdns = mdns::tokio::Behaviour::new(mdns::Config::default(), local_peer_id).unwrap();

            network::StorageBehaviour {
                gossipsub,
                kademlia,
                identify,
                mdns,
                req_resp: request_response::cbor::Behaviour::new(
                    [(libp2p::StreamProtocol::new("/feedo/chunks/1.0.0"), request_response::ProtocolSupport::Full)],
                    request_response::Config::default(),
                ),
            }
        })?
        .with_swarm_config(|c| c.with_idle_connection_timeout(Duration::from_secs(60)))
        .build();
    let p2p_port: u16 = std::env::var("P2P_PORT")
        .unwrap_or_else(|_| "8040".to_string())
        .parse()
        .unwrap_or(8040);
    swarm.listen_on(format!("/ip4/0.0.0.0/udp/{}/quic-v1", p2p_port).parse()?)?;
    if let Ok(nodes_csv) = std::env::var("BOOTSTRAP_NODES") {
        for s in nodes_csv.split(',') {
            let s = s.trim();
            if s.is_empty() { continue; }
            match s.parse::<libp2p::Multiaddr>() {
                Ok(addr) => {
                    // Extract PeerId from Multiaddr
                    let mut peer_id = None;
                    for p in addr.iter() {
                        if let libp2p::multiaddr::Protocol::P2p(hash) = p {
                            peer_id = PeerId::from_multihash(hash).ok();
                        }
                    }
                    
                    if let Some(pid) = peer_id {
                        swarm.behaviour_mut().kademlia.add_address(&pid, addr.clone());
                        println!("Added Kademlia bootstrap node: {} with peer id: {}", addr, pid);
                    } else {
                        println!("Warning: No PeerId found in bootstrap multiaddr: {}", addr);
                    }

                    match swarm.dial(addr.clone()) {
                        Ok(()) => println!("Dialing bootstrap node: {}", addr),
                        Err(e) => println!("Error dialing {}: {:?}", addr, e),
                    }
                }
                Err(e) => println!("Invalid bootstrap multiaddr '{}': {:?}", s, e),
            }
        }
        
        println!("Triggering initial Kademlia bootstrap...");
        let _ = swarm.behaviour_mut().kademlia.bootstrap();
    }

    let (swarm_tx, swarm_rx) = mpsc::unbounded_channel();
    let (gossip_tx, _) = tokio::sync::broadcast::channel::<(String, Vec<u8>)>(1024);
    
    let key_clone = local_key.clone();
    let sf_clone2 = storage_full.clone();
    let gossip_tx_clone = gossip_tx.clone();
    let quota_clone = quota_manager.clone();
    tokio::spawn(async move {
        crate::swarm_loop::run_swarm(swarm, swarm_rx, key_clone, sf_clone2, gossip_tx_clone, quota_clone).await;
    });

    let grpc_port: u16 = std::env::var("GRPC_PORT")
        .unwrap_or_else(|_| "50052".to_string())
        .parse()
        .unwrap_or(50052);
    let http_port: u16 = std::env::var("HTTP_PORT")
        .unwrap_or_else(|_| "3001".to_string())
        .parse()
        .unwrap_or(3001);
    let grpc_addr: SocketAddr = format!("0.0.0.0:{}", grpc_port).parse().unwrap();
    let http_addr: SocketAddr = format!("0.0.0.0:{}", http_port).parse().unwrap();

    let storage_service = MyStorageService {
        swarm_tx: swarm_tx.clone(),
    };

    println!("Starting gRPC Storage Service on {}", grpc_addr);
    let grpc_server = Server::builder()
        .add_service(StorageServiceServer::new(storage_service))
        .serve(grpc_addr);

    let app_state = AppState { 
        swarm_tx,
        recent_hashes: Arc::new(std::sync::Mutex::new(Vec::new())),
        gossip_tx,
        quota_manager,
    };
    let cors = tower_http::cors::CorsLayer::permissive();
    let app = Router::new()
        .route("/upload", post(handle_upload))
        .route("/api/v1/ingest/post", post(handle_json_ingest))
        .route("/api/v1/ingest/batch", post(handle_batch_json_ingest))
        .route("/api/v1/pubsub/publish", post(handle_publish))
        .route("/api/v1/pubsub/subscribe/:topic", get(handle_subscribe))
        .route("/api/files/recent", get(handle_recent_files))
        .route("/download/:hash", get(handle_download))
        .route("/delete/:hash", delete(handle_delete))
        .route("/api/v1/quota", get(handle_quota))
        .route("/api/v1/peers", get(handle_peers))
        .with_state(app_state)
        .layer(cors)
        .layer(axum::extract::DefaultBodyLimit::max(100 * 1024 * 1024));

    let listener = tokio::net::TcpListener::bind(http_addr).await.unwrap();
    println!("Starting HTTP server on {}", http_addr);
    let http_server = axum::serve(listener, app);

    tokio::select! {
        res = grpc_server => println!("gRPC server exited with {:?}", res),
        res = http_server.into_future() => println!("HTTP server exited with {:?}", res),
    }

    Ok(())
}
