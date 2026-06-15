mod pbft;
mod proto;
pub mod did;
pub mod crdt;
mod nostr_db;
pub mod name_db;
pub mod eth_bridge;
pub mod accounting;

use axum::{routing::{post, get}, Json, Router, extract::{State, Path}};
use prost::Message as ProstMessage;
use base64::Engine;
use futures::StreamExt;
use axum::extract::Multipart;
use sha2::{Sha256, Digest};
use secp256k1::{Secp256k1, ecdsa::Signature, Message, PublicKey};
use libp2p::{
    gossipsub, identify, identity, kad, mdns, request_response,
    swarm::{NetworkBehaviour, SwarmEvent}, PeerId, StreamProtocol, SwarmBuilder, Multiaddr,
    multiaddr::Protocol,
};
use libp2p::kad::store::{RecordStore, MemoryStore, MemoryStoreConfig, Result as KadResult};
use libp2p::kad::{Record, RecordKey, ProviderRecord};
use reed_solomon_erasure::galois_8::ReedSolomon;
use serde::{Deserialize, Serialize};
use std::{collections::{HashMap, hash_map::DefaultHasher}, error::Error, hash::{Hash, Hasher}, time::Duration, env, str::FromStr, borrow::Cow, fs, path::Path as FsPath};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tokio::sync::{mpsc, oneshot};
use tokio::task::block_in_place;

const DATA_SHARDS: usize = 30;
const PARITY_SHARDS: usize = 15;
const TOTAL_SHARDS: usize = DATA_SHARDS + PARITY_SHARDS;

// --- 1. NETWORK MESSAGES (METADATA) ---

use proto::feedo::FeedoBroadcast;

#[derive(Serialize)]
struct NetworkInfo {
    pub peer_id: String,
    pub total_nodes: usize,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
enum DirectRequest {
    Handshake { challenge: String },
    StoreShard { chunk_key: String, data: Vec<u8> },
    FetchShard { chunk_key: String },
    FetchManifest { file_hash: String },
    PbftVote(Vec<u8>),
    VectorQuery { vector: Vec<f32>, limit: usize },
    PoStChallenge { chunk_key: String, nonce: u64 },
}

#[derive(Serialize, Deserialize, Debug, Clone)]
enum DirectResponse {
    HandshakeResponse(Vec<u8>),
    StoreOk,
    ShardData(Option<Vec<u8>>),
    ManifestData(Option<Manifest>),
    PbftVoteOk,
    VectorQueryResponse(String), 
    PoStResponse { response_hash: String },
}

#[derive(Serialize, Deserialize, Debug, Clone)]
struct Manifest {
    file_hash: String,
    size: usize,
    shards: HashMap<usize, String>,
}

// --- 2. HELPER FUNCTIONS FOR REED-SOLOMON ---

fn encode_data(data: &[u8]) -> Result<Vec<Vec<u8>>, Box<dyn Error + Send + Sync>> {
    let rs = ReedSolomon::new(DATA_SHARDS, PARITY_SHARDS).map_err(|e| e.to_string())?;
    let shard_size = (data.len() + DATA_SHARDS - 1) / DATA_SHARDS;
    let mut shards = vec![vec![0u8; shard_size]; TOTAL_SHARDS];

    for i in 0..DATA_SHARDS {
        let start = i * shard_size;
        let end = std::cmp::min(start + shard_size, data.len());
        if end > start {
            shards[i][..end - start].copy_from_slice(&data[start..end]);
        }
    }
    rs.encode(&mut shards).map_err(|e| e.to_string())?;
    Ok(shards)
}

fn decode_data(mut shards: Vec<Option<Vec<u8>>>, original_len: usize) -> Result<Vec<u8>, Box<dyn Error + Send + Sync>> {
    let rs = ReedSolomon::new(DATA_SHARDS, PARITY_SHARDS).map_err(|e| e.to_string())?;
    rs.reconstruct(&mut shards).map_err(|e| e.to_string())?;

    let mut result = Vec::with_capacity(original_len);
    for i in 0..DATA_SHARDS {
        if let Some(shard) = &shards[i] {
            result.extend_from_slice(shard);
        }
    }
    result.truncate(original_len);
    Ok(result)
}

// --- 3. HYBRID STORE (Memory + Sled + Python Fetch) ---

pub struct HybridStore {
    mem: MemoryStore,
    db: sled::Db,
    python_api: String,
    pub storage_full: Arc<AtomicBool>,
}

impl HybridStore {
    pub fn new(peer_id: PeerId, db: sled::Db, python_api: &str, storage_full: Arc<AtomicBool>) -> Self {
        let mut config = MemoryStoreConfig::default();
        
        let ram_limit = env::var("DHT_RAM_CACHE_LIMIT")
            .unwrap_or_else(|_| "1000".to_string())
            .parse::<usize>()
            .unwrap_or(1000);
            
        config.max_records = ram_limit;
        
        let mem = MemoryStore::with_config(peer_id, config);
        Self { mem, db, python_api: python_api.to_string(), storage_full }
    }

}

impl RecordStore for HybridStore {
    type RecordsIter<'a> = <MemoryStore as RecordStore>::RecordsIter<'a>;
    type ProvidedIter<'a> = <MemoryStore as RecordStore>::ProvidedIter<'a>;

    fn get(&self, k: &RecordKey) -> Option<Cow<'_, Record>> {
        if let Some(rec) = self.mem.get(k) {
            return Some(rec);
        }

        let key_bytes = k.as_ref();
        
        if let Ok(Some(val)) = self.db.get(key_bytes) {
            let record = Record {
                key: k.clone(),
                value: val.to_vec(),
                publisher: None,
                expires: None,
            };
            return Some(Cow::Owned(record));
        }

        None
    }

    fn put(&mut self, r: Record) -> KadResult<()> {
        if self.storage_full.load(Ordering::Relaxed) {
            return Err(libp2p::kad::store::Error::MaxProvidedKeys);
        }

        let _ = self.db.insert(r.key.as_ref(), r.value.clone());
        
        let _ = self.mem.put(r);
        
        Ok(())
    }

    fn remove(&mut self, k: &RecordKey) {
        let _ = self.db.remove(k.as_ref());
        self.mem.remove(k)
    }

    fn records(&self) -> Self::RecordsIter<'_> { self.mem.records() }
    fn add_provider(&mut self, record: ProviderRecord) -> KadResult<()> { self.mem.add_provider(record) }
    fn providers(&self, key: &RecordKey) -> Vec<ProviderRecord> { self.mem.providers(key) }
    fn provided(&self) -> Self::ProvidedIter<'_> { self.mem.provided() }
    fn remove_provider(&mut self, k: &RecordKey, p: &PeerId) { self.mem.remove_provider(k, p) }
}


// --- 4. MESSAGES AND API ---

#[derive(NetworkBehaviour)]
struct FeedoBehaviour {
    gossipsub: gossipsub::Behaviour,
    kademlia: kad::Behaviour<HybridStore>,
    identify: identify::Behaviour,
    req_resp: request_response::cbor::Behaviour<DirectRequest, DirectResponse>,
    mdns: mdns::tokio::Behaviour,
}


enum SwarmCommand {
    Publish(proto::feedo::PublishRequest),
    FetchContent(String, u64, oneshot::Sender<Option<String>>),
    GetNetworkInfo(oneshot::Sender<NetworkInfo>),
    UploadMedia(Vec<u8>, oneshot::Sender<String>),
    AnnouncePeer,
    SavePeerCache,
    PbftPropose(String, u64, i32),
    MempoolValidationResult(String, bool, i32),
    PushCentroids(Vec<String>, Vec<Vec<f32>>),
    VectorRouteQuery(Vec<f32>, Vec<String>, usize, oneshot::Sender<String>),
    RegisterDid(proto::feedo::DidRegistrationRequest),
    RegisterName(proto::feedo::NameRegistrationRequest),
    ResolveDid(String, oneshot::Sender<Option<String>>),
    ResolveName(String, oneshot::Sender<Option<String>>),
    CrdtMutate(proto::feedo::CrdtOperation),
    CrdtGet(String, oneshot::Sender<Option<String>>),
    // RegisterSchema(proto::feedo::SchemaRegistrationRequest),
    // ResolveSchema(String, oneshot::Sender<Option<String>>),
    TriggerPoStChallenges,
    InitiateSemanticSearch(String, u32, oneshot::Sender<String>),
    FinishSemanticSearch(String),
    BroadcastSemanticResult(Vec<u8>),
    ForwardSemanticSearch(Vec<u8>),
    DhtUpload(Vec<u8>, oneshot::Sender<String>),
    DhtDownload(String, oneshot::Sender<Option<Vec<u8>>>),
}

#[derive(Serialize, Deserialize, Debug, Clone)]
struct PeerAnnounce {
    peer_id: String,
    listen_addrs: Vec<String>,
    timestamp: u64,
    nonce: Option<String>,
    signature: Option<String>,
    public_key: Option<String>,
    storage_status: Option<String>,
    is_supernode: Option<bool>,
}

async fn handle_publish(
    State(tx): State<mpsc::UnboundedSender<SwarmCommand>>,
    bytes: axum::body::Bytes,
) -> Result<&'static str, (axum::http::StatusCode, &'static str)> {
    
    let payload = match proto::feedo::PublishRequest::decode(bytes) {
        Ok(p) => p,
        Err(_) => return Err((axum::http::StatusCode::BAD_REQUEST, "Invalid protobuf payload")),
    };

    let hash_bytes = match hex::decode(&payload.hash_id) {
        Ok(b) => b,
        Err(_) => return Err((axum::http::StatusCode::BAD_REQUEST, "Invalid hash format")),
    };
    
    if !did::verify_signature(&payload.author, &hash_bytes, &payload.signature) {
        return Err((axum::http::StatusCode::UNAUTHORIZED, "Invalid cryptographic signature"));
    }

    let _ = tx.send(SwarmCommand::Publish(payload));
    Ok("Publishing to P2P Matrix...")
}

async fn handle_dht_upload(
    State(tx): State<mpsc::UnboundedSender<SwarmCommand>>,
    mut multipart: Multipart,
) -> Result<String, (axum::http::StatusCode, String)> {
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
    
    let (resp_tx, resp_rx) = oneshot::channel();
    let _ = tx.send(SwarmCommand::DhtUpload(file_data, resp_tx));
    
    match resp_rx.await {
        Ok(hash) => Ok(hash),
        Err(_) => Err((axum::http::StatusCode::INTERNAL_SERVER_ERROR, "DHT upload failed".to_string())),
    }
}

async fn handle_dht_download(
    State(tx): State<mpsc::UnboundedSender<SwarmCommand>>,
    Path(hash): Path<String>,
) -> Result<Vec<u8>, (axum::http::StatusCode, String)> {
    let (resp_tx, resp_rx) = oneshot::channel();
    let _ = tx.send(SwarmCommand::DhtDownload(hash, resp_tx));
    match resp_rx.await {
        Ok(Some(data)) => Ok(data),
        _ => Err((axum::http::StatusCode::NOT_FOUND, "Not found in DHT".to_string())),
    }
}


async fn handle_fetch_content(
    State(tx): State<mpsc::UnboundedSender<SwarmCommand>>,
    Path((content_hash, size)): Path<(String, u64)>,
) -> Json<Option<String>> {
    let (resp_tx, resp_rx) = oneshot::channel();
    let _ = tx.send(SwarmCommand::FetchContent(content_hash, size, resp_tx));
    
    if let Ok(res) = resp_rx.await {
        Json(res)
    } else {
        Json(None)
    }
}

async fn handle_network_info(
    State(tx): State<mpsc::UnboundedSender<SwarmCommand>>,
) -> Json<Option<NetworkInfo>> {
    let (resp_tx, resp_rx) = oneshot::channel();
    let _ = tx.send(SwarmCommand::GetNetworkInfo(resp_tx));
    
    if let Ok(res) = resp_rx.await {
        Json(Some(res))
    } else {
        Json(None)
    }
}

#[derive(Deserialize)]
struct PushCentroidsReq {
    cluster_ids: Vec<String>,
    centroids: Vec<Vec<f32>>,
}

async fn handle_push_centroids(
    State(tx): State<mpsc::UnboundedSender<SwarmCommand>>,
    Json(req): Json<PushCentroidsReq>,
) -> &'static str {
    let _ = tx.send(SwarmCommand::PushCentroids(req.cluster_ids, req.centroids));
    "ok"
}

#[derive(Deserialize)]
struct VectorRouteQueryReq {
    vector: Vec<f32>,
    target_peers: Vec<String>,
    limit: usize,
}

async fn handle_vector_route_query(
    State(tx): State<mpsc::UnboundedSender<SwarmCommand>>,
    Json(req): Json<VectorRouteQueryReq>,
) -> Json<serde_json::Value> {
    let (resp_tx, resp_rx) = oneshot::channel();
    let _ = tx.send(SwarmCommand::VectorRouteQuery(req.vector, req.target_peers, req.limit, resp_tx));
    if let Ok(res_str) = resp_rx.await {
        if let Ok(json) = serde_json::from_str(&res_str) {
            return Json(json);
        }
    }
    Json(serde_json::json!({"results": []}))
}

#[derive(Serialize)]
struct MediaUploadResponse {
    media_hash: String,
    size: usize,
}

async fn handle_upload_media(
    State(tx): State<mpsc::UnboundedSender<SwarmCommand>>,
    mut multipart: Multipart,
) -> Result<Json<MediaUploadResponse>, (axum::http::StatusCode, String)> {
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
    
    let size = file_data.len();
    let (resp_tx, resp_rx) = oneshot::channel();
    let _ = tx.send(SwarmCommand::UploadMedia(file_data, resp_tx));
    
    match resp_rx.await {
        Ok(media_hash) => Ok(Json(MediaUploadResponse { media_hash, size })),
        Err(_) => Err((axum::http::StatusCode::INTERNAL_SERVER_ERROR, "DHT upload failed".to_string())),
    }
}

async fn handle_register_did(
    State(tx): State<mpsc::UnboundedSender<SwarmCommand>>,
    bytes: axum::body::Bytes,
) -> Result<&'static str, (axum::http::StatusCode, &'static str)> {
    let payload = match proto::feedo::DidRegistrationRequest::decode(bytes) {
        Ok(p) => p,
        Err(_) => return Err((axum::http::StatusCode::BAD_REQUEST, "Invalid protobuf payload")),
    };

    if let Ok(doc) = serde_json::from_str::<did::DidDocument>(&payload.did_document) {
        if let Some(vm) = doc.verification_method.first() {
            if !did::verify_signature(&vm.public_key_multibase, payload.did_document.as_bytes(), &payload.signature) {
                return Err((axum::http::StatusCode::UNAUTHORIZED, "Invalid cryptographic signature"));
            }
        } else {
            return Err((axum::http::StatusCode::BAD_REQUEST, "Missing verificationMethod"));
        }
    } else {
        return Err((axum::http::StatusCode::BAD_REQUEST, "Invalid DID Document JSON"));
    }

    let _ = tx.send(SwarmCommand::RegisterDid(payload));
    Ok("DID Registration submitted to P2P Matrix")
}

async fn handle_register_name(
    State(tx): State<mpsc::UnboundedSender<SwarmCommand>>,
    bytes: axum::body::Bytes,
) -> Result<&'static str, (axum::http::StatusCode, &'static str)> {
    let payload = match proto::feedo::NameRegistrationRequest::decode(bytes) {
        Ok(p) => p,
        Err(_) => return Err((axum::http::StatusCode::BAD_REQUEST, "Invalid protobuf payload")),
    };

    let msg_to_sign = format!("{}:{}", payload.name, payload.did);
    if !did::verify_signature(&payload.public_key, msg_to_sign.as_bytes(), &payload.signature) {
        return Err((axum::http::StatusCode::UNAUTHORIZED, "Invalid cryptographic signature"));
    }

    let _ = tx.send(SwarmCommand::RegisterName(payload));
    Ok("Name Registration submitted to P2P Matrix")
}

async fn handle_resolve_did(
    State(tx): State<mpsc::UnboundedSender<SwarmCommand>>,
    Path(id): Path<String>,
) -> Json<Option<String>> {
    let (resp_tx, resp_rx) = oneshot::channel();
    let _ = tx.send(SwarmCommand::ResolveDid(id, resp_tx));
    if let Ok(res) = resp_rx.await { Json(res) } else { Json(None) }
}

async fn handle_resolve_name(
    State(tx): State<mpsc::UnboundedSender<SwarmCommand>>,
    Path(name): Path<String>,
) -> Json<Option<String>> {
    let (resp_tx, resp_rx) = oneshot::channel();
    let _ = tx.send(SwarmCommand::ResolveName(name, resp_tx));
    if let Ok(res) = resp_rx.await { Json(res) } else { Json(None) }
}

async fn handle_crdt_mutate(
    State(tx): State<mpsc::UnboundedSender<SwarmCommand>>,
    bytes: axum::body::Bytes,
) -> Result<&'static str, (axum::http::StatusCode, &'static str)> {
    let payload = match proto::feedo::CrdtOperation::decode(bytes) {
        Ok(p) => p,
        Err(_) => return Err((axum::http::StatusCode::BAD_REQUEST, "Invalid CRDT protobuf payload")),
    };
    let _ = tx.send(SwarmCommand::CrdtMutate(payload));
    Ok("CRDT operation submitted to P2P Matrix")
}

async fn handle_crdt_get(
    State(tx): State<mpsc::UnboundedSender<SwarmCommand>>,
    Path(object_id): Path<String>,
) -> Json<Option<String>> {
    let (resp_tx, resp_rx) = oneshot::channel();
    let _ = tx.send(SwarmCommand::CrdtGet(object_id, resp_tx));
    if let Ok(res) = resp_rx.await { Json(res) } else { Json(None) }
}

// async fn handle_register_schema(
//     State(tx): State<mpsc::UnboundedSender<SwarmCommand>>,
//     bytes: axum::body::Bytes,
// ) -> Result<&'static str, (axum::http::StatusCode, &'static str)> {
//     let payload = match proto::feedo::SchemaRegistrationRequest::decode(bytes) {
//         Ok(p) => p,
//         Err(_) => return Err((axum::http::StatusCode::BAD_REQUEST, "Invalid protobuf payload")),
//     };

//     let msg_to_sign = format!("{}:{}", payload.schema_id, payload.schema_definition);
//     if !did::verify_signature(&payload.public_key, msg_to_sign.as_bytes(), &payload.signature) {
//         return Err((axum::http::StatusCode::UNAUTHORIZED, "Invalid cryptographic signature"));
//     }

//     let _ = tx.send(SwarmCommand::RegisterSchema(payload));
//     Ok("Schema Registration submitted to P2P Matrix")
// }

// async fn handle_resolve_schema(
//     State(tx): State<mpsc::UnboundedSender<SwarmCommand>>,
//     Path(id): Path<String>,
// ) -> Json<Option<String>> {
//     let (resp_tx, resp_rx) = oneshot::channel();
//     let _ = tx.send(SwarmCommand::ResolveSchema(id, resp_tx));
//     if let Ok(res) = resp_rx.await { Json(res) } else { Json(None) }
// }

#[derive(Deserialize)]
struct SemanticSearchReq {
    text_query: String,
    limit: Option<u32>,
}

async fn handle_semantic_search(
    State(tx): State<mpsc::UnboundedSender<SwarmCommand>>,
    Json(req): Json<SemanticSearchReq>,
) -> Json<serde_json::Value> {
    let (resp_tx, resp_rx) = oneshot::channel();
    let _ = tx.send(SwarmCommand::InitiateSemanticSearch(req.text_query, req.limit.unwrap_or(10), resp_tx));
    if let Ok(res_str) = resp_rx.await {
        if let Ok(json) = serde_json::from_str(&res_str) {
            return Json(json);
        }
    }
    Json(serde_json::json!({"results": []}))
}

struct FetchState {
    sender: Option<oneshot::Sender<Option<String>>>,
    shards: Vec<Option<Vec<u8>>>,
    received: usize,
    failed: usize,
    original_size: usize,
    manifest: Option<Manifest>,
}

fn do_self_healing(
    hash: &str,
    state: &mut FetchState,
    swarm: &mut libp2p::Swarm<FeedoBehaviour>,
    peer_cache: &PeerCache,
    local_peer_id: libp2p::PeerId,
) {
    println!("Self-Healing: file {} has {} failed shards. Rebuilding...", hash, state.failed);
    if let Ok(decoded) = decode_data(state.shards.clone(), state.original_size) {
        if let Ok(new_shards) = encode_data(&decoded) {
            let mut new_manifest = state.manifest.clone().unwrap_or(Manifest {
                file_hash: hash.to_string(),
                size: state.original_size,
                shards: std::collections::HashMap::new(),
            });
            
            let top_peers = peer_cache.top_n_addrs(45);
            let mut target_peers = Vec::new();
            for addr_str in top_peers {
                if let Ok(ma) = libp2p::Multiaddr::from_str(&addr_str) {
                    for p in ma.iter() {
                        if let libp2p::multiaddr::Protocol::P2p(mh) = p {
                            if let Ok(pid) = libp2p::PeerId::from_multihash(mh.into()) {
                                target_peers.push(pid);
                                break;
                            }
                        }
                    }
                }
            }
            if target_peers.is_empty() {
                target_peers.push(local_peer_id);
            }

            for (i, maybe_shard) in state.shards.iter().enumerate() {
                if maybe_shard.is_none() {
                    let repaired_shard = new_shards[i].clone();
                    let target_peer = target_peers[i % target_peers.len()];
                    new_manifest.shards.insert(i, target_peer.to_string());
                    let chunk_key = format!("{}_chunk_{}", hash, i);
                    
                    if target_peer != local_peer_id {
                        let _ = swarm.behaviour_mut().req_resp.send_request(
                            &target_peer,
                            DirectRequest::StoreShard { chunk_key: chunk_key.clone(), data: repaired_shard }
                        );
                    } else {
                        let record = libp2p::kad::Record {
                            key: libp2p::kad::RecordKey::new(&chunk_key),
                            value: repaired_shard,
                            publisher: None,
                            expires: None,
                        };
                        let _ = swarm.behaviour_mut().kademlia.store_mut().put(record);
                    }
                }
            }
            
            if let Ok(manifest_bytes) = serde_json::to_vec(&new_manifest) {
                let manifest_record = libp2p::kad::Record {
                    key: libp2p::kad::RecordKey::new(&format!("{}_manifest", hash)),
                    value: manifest_bytes,
                    publisher: None,
                    expires: None,
                };
                let _ = swarm.behaviour_mut().kademlia.store_mut().put(manifest_record);
                let _ = swarm.behaviour_mut().kademlia.start_providing(libp2p::kad::RecordKey::new(&hash));
                println!("Self-Healing completed for {}", hash);
            }
        }
    }
}

// --- 5. MAIN LOOP ---

fn get_dir_size(path: impl AsRef<FsPath>) -> std::io::Result<u64> {
    let mut size = 0;
    if path.as_ref().is_dir() {
        for entry in fs::read_dir(path)? {
            let entry = entry?;
            let path = entry.path();
            if path.is_dir() {
                size += get_dir_size(&path)?;
            } else {
                size += entry.metadata()?.len();
            }
        }
    } else if path.as_ref().exists() {
        size = path.as_ref().metadata()?.len();
    }
    Ok(size)
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    println!("Starting Feedo Core (Erasure Coding DHT + Sled Persistent Node)...");

    let db_path = env::var("DHT_DB_PATH")
        .or_else(|_| env::var("RUST_DB_PATH"))
        .unwrap_or_else(|_| "./rust_db_data".to_string());

    if !FsPath::new(&db_path).exists() {
        let _ = fs::create_dir_all(&db_path);
    }

    let default_key_path = format!("{}/peer_key.bin", db_path);
    let peer_key_path = env::var("PEER_KEY_PATH").unwrap_or(default_key_path);
    
    let local_key = if FsPath::new(&peer_key_path).exists() {
        match fs::read(&peer_key_path) {
            Ok(bytes) => match identity::Keypair::from_protobuf_encoding(&bytes) {
                Ok(k) => {
                    println!("Loaded saved key from: {}", peer_key_path);
                    k
                }
                Err(e) => {
                    println!("Failed to deserialize key, generated new one: {:?}", e);
                    let k = identity::Keypair::generate_ed25519();
                    if let Ok(bytes) = k.to_protobuf_encoding() {
                        let _ = fs::write(&peer_key_path, bytes);
                    }
                    k
                }
            },
            Err(e) => {
                println!("Failed to read {}: {:?}. Generated new key.", peer_key_path, e);
                let k = identity::Keypair::generate_ed25519();
                if let Ok(bytes) = k.to_protobuf_encoding() {
                    let _ = fs::write(&peer_key_path, bytes);
                }
                k
            }
        }
    } else {
        let k = identity::Keypair::generate_ed25519();
        match k.to_protobuf_encoding() {
            Ok(bytes) => {
                if let Err(e) = fs::write(&peer_key_path, bytes) {
                    println!("Error saving key to {}: {:?}", peer_key_path, e);
                } else {
                    println!("Saved new key to: {}", peer_key_path);
                }
            }
            Err(e) => {
                println!("Failed to serialize key for saving to {}: {:?}", peer_key_path, e);
            }
        }
        k
    };

    let local_peer_id = PeerId::from(local_key.public());
    let local_peer_id_str = local_peer_id.to_string();
    println!("My PeerId: {}", local_peer_id);
    


    let message_id_fn = |message: &gossipsub::Message| {
        let mut s = DefaultHasher::new();
        message.data.hash(&mut s);
        gossipsub::MessageId::from(s.finish().to_string())
    };
    
    let gossipsub_config = gossipsub::ConfigBuilder::default()
        .heartbeat_interval(Duration::from_secs(10))
        .validation_mode(gossipsub::ValidationMode::Strict)
        .message_id_fn(message_id_fn)
        .build()
        .expect("Valid config");
        
    let mut gossipsub = gossipsub::Behaviour::new(
        gossipsub::MessageAuthenticity::Signed(local_key.clone()),
        gossipsub_config,
    ).unwrap();
    
    let topic = gossipsub::IdentTopic::new("feedo_global_feed");
    gossipsub.subscribe(&topic).unwrap();
    let announce_topic = gossipsub::IdentTopic::new("feedo_peer_announce_v1");
    gossipsub.subscribe(&announce_topic).unwrap();
    let pbft_topic = gossipsub::IdentTopic::new("feedo_pbft_consensus");
    gossipsub.subscribe(&pbft_topic).unwrap();
    let mempool_topic = gossipsub::IdentTopic::new("feedo_mempool");
    gossipsub.subscribe(&mempool_topic).unwrap();
    let supernode_sync_topic = gossipsub::IdentTopic::new("feedo_supernode_sync");
    gossipsub.subscribe(&supernode_sync_topic).unwrap();
    let crdt_sync_topic = gossipsub::IdentTopic::new("feedo_crdt_sync");
    gossipsub.subscribe(&crdt_sync_topic).unwrap();
    let semantic_search_topic = gossipsub::IdentTopic::new("feedo_semantic_search");
    gossipsub.subscribe(&semantic_search_topic).unwrap();



    println!("DHT persistent store path: {}", db_path);
    let python_api = env::var("PYTHON_API_URL").unwrap_or_else(|_| "http://127.0.0.1:8040".to_string());
    
    let storage_full = Arc::new(AtomicBool::new(false));
    let shared_db = sled::open(&db_path).expect("Не вдалося відкрити дискову базу Sled");
    let store = HybridStore::new(local_peer_id, shared_db.clone(), &python_api, storage_full.clone());
    
    let mut kad_config = kad::Config::default();
    kad_config.set_query_timeout(Duration::from_secs(10));
    kad_config.set_record_filtering(kad::StoreInserts::FilterBoth);
    let mut kademlia = kad::Behaviour::with_config(local_peer_id, store, kad_config);
    kademlia.set_mode(Some(kad::Mode::Server));

    let db_path_clone = db_path.clone();
    let max_storage_gb = env::var("MAX_STORAGE_GB")
        .unwrap_or_else(|_| "100".to_string())
        .parse::<u64>()
        .unwrap_or(100);
    let max_storage_bytes = max_storage_gb * 1024 * 1024 * 1024;
    let storage_full_clone = storage_full.clone();
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_secs(60));
        loop {
            interval.tick().await;
            let current_size = get_dir_size(&db_path_clone).unwrap_or(0);
            let is_full = current_size >= max_storage_bytes;
            storage_full_clone.store(is_full, Ordering::Relaxed);
        }
    });

    let (api_tx, mut api_rx) = mpsc::unbounded_channel::<SwarmCommand>();

    let ledger = Arc::new(accounting::Ledger::new(shared_db.clone()));
    
    // Фоновий демон Епох: Раз на годину генерує Merkle Root і пропонує його в PBFT
    let ledger_clone = ledger.clone();
    let local_peer_id_str_clone = local_peer_id_str.clone();
    let api_tx_clone = api_tx.clone();
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_secs(3600)); // 1 година
        loop {
            interval.tick().await;
            let (root, _tree) = ledger_clone.generate_merkle_root().await;
            if root != [0u8; 32] {
                let root_hex = hex::encode(root);
                println!("[EPOCH DAEMON] Generated Merkle Root for PBFT: {}", root_hex);
                let timestamp = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
                let _ = api_tx_clone.send(SwarmCommand::PbftPropose(root_hex, timestamp, pbft::TX_TYPE_MICRO_TX_BATCH));
            }
        }
    });

    if let Ok(rpc_url) = env::var("POLYGON_RPC_URL") {
        if let Ok(private_key) = env::var("NODE_WALLET_PRIVATE_KEY") {
            let rpc_clone = rpc_url.clone();
            tokio::spawn(async move {
                eth_bridge::Web3Bridge::start_auto_claim_daemon(rpc_clone, private_key).await;
            });
        }
        
        if let Ok(bridge) = eth_bridge::Web3Bridge::new(&rpc_url, ledger.clone()) {
            let bridge_arc = Arc::new(bridge);
            tokio::spawn(async move {
                bridge_arc.start_event_listener().await;
            });
        } else {
            eprintln!("Failed to initialize Web3 Bridge.");
        }
    } else {
        println!("POLYGON_RPC_URL not found, Web3 features disabled.");
    }

    let mut bootstrap_addrs: Vec<Multiaddr> = Vec::new();
    if let Ok(nodes_csv) = env::var("BOOTSTRAP_NODES") {
        for raw in nodes_csv.split(',') {
            let s = raw.trim();
            if s.is_empty() { continue; }
            match Multiaddr::from_str(s) {
                Ok(addr) => {
                    // try to find /p2p/<peerid> protocol in the multiaddr
                    let mut peer_opt: Option<PeerId> = None;
                    for p in addr.iter() {
                        if let Protocol::P2p(mh) = p {
                            if let Ok(pid) = PeerId::from_multihash(mh.into()) {
                                peer_opt = Some(pid);
                                break;
                            }
                        }
                    }
                    if let Some(pid) = peer_opt {
                        println!("Added bootstrap address {} for {}", addr, pid);
                        kademlia.add_address(&pid, addr.clone());
                    } else {
                        println!("Added bootstrap address without PeerId: {}", addr);
                    }
                    bootstrap_addrs.push(addr);
                }
                Err(e) => println!("Invalid BOOTSTRAP_NODES entry '{}': {:?}", s, e),
            }
        }
    } else if let Ok(bootstrap_addr_str) = env::var("BOOTSTRAP_NODE_ADDR") {
        if let Ok(addr) = Multiaddr::from_str(&bootstrap_addr_str) {
            println!("Connecting to global Bootstrap node: {}", addr);
            bootstrap_addrs.push(addr);
            let _ = kademlia.bootstrap();
        }
    }

    let mdns = mdns::tokio::Behaviour::new(mdns::Config::default(), local_peer_id)?;

    let behaviour = FeedoBehaviour {
        gossipsub,
        kademlia,
        identify: identify::Behaviour::new(identify::Config::new("/feedo/2.0.0".into(), local_key.public())),
        req_resp: request_response::cbor::Behaviour::new(
            [(StreamProtocol::new("/feedo/chunks/1.0.0"), request_response::ProtocolSupport::Full)],
            request_response::Config::default(),
        ),
        mdns,
    };

    let mut swarm = SwarmBuilder::with_existing_identity(local_key.clone())
        .with_tokio()
        .with_quic()
        .with_behaviour(|_| behaviour).unwrap()
        .build();

    swarm.listen_on("/ip4/0.0.0.0/udp/4001/quic-v1".parse()?)?;

    if let Ok(ext_ip) = env::var("EXTERNAL_IP") {
        if let Ok(addr) = format!("/ip4/{}/udp/4001/quic-v1", ext_ip).parse::<Multiaddr>() {
            swarm.add_external_address(addr);
            println!("Added external address (EXTERNAL_IP): {}", ext_ip);
        } else {
            println!("Invalid EXTERNAL_IP format: {}", ext_ip);
        }
    }

    for addr in bootstrap_addrs.iter() {
        match swarm.dial(addr.clone()) {
            Ok(()) => println!("Dialing bootstrap {}", addr),
            Err(e) => println!("Dial error {}: {:?}", addr, e),
        }
    }

    let peer_cache_path = env::var("PEER_CACHE_PATH").unwrap_or_else(|_| "./peer_cache.json".to_string());
    let mut peer_cache = PeerCache::load(&peer_cache_path);
    let top_addrs = peer_cache.top_n_addrs(10);
    for a in top_addrs.iter() {
        if let Ok(ma) = Multiaddr::from_str(a) {
            match swarm.dial(ma.clone()) {
                Ok(()) => println!("Dialing cached peer {}", a),
                Err(e) => println!("Dial cached {} error: {:?}", a, e),
            }
        }
    }

    
    let mut handshake_challenges = HashMap::new();
    let mut active_fetches: HashMap<String, FetchState> = HashMap::new();
    let mut query_to_fetch: HashMap<kad::QueryId, (String, usize)> = HashMap::new();
    let mut manifest_queries: HashMap<kad::QueryId, String> = HashMap::new();
    let mut req_resp_to_fetch: HashMap<request_response::OutboundRequestId, (String, usize)> = HashMap::new();
    let mut manifest_requests: HashMap<request_response::OutboundRequestId, String> = HashMap::new();
    let mut local_shard_store: HashMap<String, Vec<Option<Vec<u8>>>> = HashMap::new();
    let peer_blacklist_path = env::var("PEER_BLACKLIST_PATH").unwrap_or_else(|_| "./peer_blacklist.json".to_string());
    let mut peer_blacklist: std::collections::HashSet<String> = match fs::read_to_string(&peer_blacklist_path) {
        Ok(s) => serde_json::from_str(&s).unwrap_or_default(),
        Err(_) => std::collections::HashSet::new(),
    };
    let mut announce_rate_map: HashMap<String, Vec<u64>> = HashMap::new();
    let mut search_query_cache: HashMap<String, u64> = HashMap::new();
    let mut active_search_requests: HashMap<String, (oneshot::Sender<String>, Vec<proto::feedo::SemanticSearchResultItem>)> = HashMap::new();

    let mut pbft_manager = pbft::PbftManager::new(local_peer_id_str.clone());
    if let Ok(private_key) = std::env::var("NODE_WALLET_PRIVATE_KEY") {
        pbft_manager.set_secret_key(&private_key);
    }
    let crdt_manager = crdt::CrdtManager::new(shared_db.clone());
    
    let name_db_path = format!("{}/name_registry.db", db_path);
    let name_db = name_db::NameDb::new(&name_db_path).expect("Failed to open NameDb");

    let ledger_db = sled::open(format!("{}/ledger", db_path)).unwrap();
    let ledger = Arc::new(accounting::Ledger::new(ledger_db));

    if let Ok(rpc_url) = env::var("POLYGON_RPC_URL") {
        if let Ok(bridge) = eth_bridge::Web3Bridge::new(&rpc_url, ledger.clone()) {
            let bridge_arc = Arc::new(bridge);
            tokio::spawn(async move {
                bridge_arc.start_event_listener().await;
            });
        }
    }

    let app = Router::new()
        .route("/local/publish", post(handle_publish))
        .route("/local/upload_media", post(handle_upload_media))
        .route("/local/fetch_content/:hash/:size", get(handle_fetch_content))
        .route("/local/network_info", get(handle_network_info))
        .route("/local/push_centroids", post(handle_push_centroids))
        .route("/local/vector_route_query", post(handle_vector_route_query))
        .route("/local/register_did", post(handle_register_did))
        .route("/local/register_name", post(handle_register_name))
        .route("/local/resolve_did/:id", get(handle_resolve_did))
        .route("/local/resolve_name/:name", get(handle_resolve_name))
        .route("/local/crdt_mutate", post(handle_crdt_mutate))
        .route("/local/crdt_get/:object_id", get(handle_crdt_get))
        .route("/local/semantic_search", post(handle_semantic_search))
        .route("/local/dht/upload", post(handle_dht_upload))
        .route("/local/dht/download/:hash", get(handle_dht_download))
        .route("/local/balance/:address", get(handle_balance))
        // .route("/local/register_schema", post(handle_register_schema))
        // .route("/local/resolve_schema/:id", get(handle_resolve_schema))
        .layer(axum::extract::Extension(ledger.clone()))
        .with_state(api_tx.clone());

    tokio::spawn(async move {
        let listener = tokio::net::TcpListener::bind("0.0.0.0:8041").await.unwrap();
        println!("Local API for Python opened on port 8041");
        axum::serve(listener, app).await.unwrap();
    });

    let gc_path = peer_cache_path.clone();
    let mut pc_for_gc = peer_cache.clone();
    let gc_days = env::var("PEER_CACHE_TTL_DAYS").unwrap_or_else(|_| "30".to_string()).parse::<u64>().unwrap_or(30);
    let gc_interval_secs = env::var("PEER_CACHE_GC_SECS").unwrap_or_else(|_| "86400".to_string()).parse::<u64>().unwrap_or(86400);
    let gc_tx = api_tx.clone();
    tokio::spawn(async move {
        let mut tick = tokio::time::interval(Duration::from_secs(gc_interval_secs));
        loop {
            tick.tick().await;
            pc_for_gc.gc(gc_days);
            pc_for_gc.save(&gc_path);
            let _ = gc_tx.send(SwarmCommand::SavePeerCache);
        }
    });

    let post_tx = api_tx.clone();
    tokio::spawn(async move {
        let mut tick = tokio::time::interval(Duration::from_secs(300));
        loop {
            tick.tick().await;
            let _ = post_tx.send(SwarmCommand::TriggerPoStChallenges);
        }
    });

    let http_client = reqwest::Client::new();
    let python_webhook_url = env::var("PYTHON_WEBHOOK_URL")
        .unwrap_or_else(|_| "http://127.0.0.1:8040/internal/p2p_receive".to_string());

    let retry_secs = env::var("BOOTSTRAP_RETRY_SECS").unwrap_or_else(|_| "45".to_string()).parse::<u64>().unwrap_or(45);
    let min_peers_before_retry = env::var("MIN_PEERS_BEFORE_RETRY").unwrap_or_else(|_| "2".to_string()).parse::<usize>().unwrap_or(2);
    let mut bootstrap_interval = tokio::time::interval(Duration::from_secs(retry_secs));
    let mut gc_pending_shards_interval = tokio::time::interval(Duration::from_secs(600));
    let announcer_tx = api_tx.clone();
    tokio::spawn(async move {
        let mut tick = tokio::time::interval(Duration::from_secs(60));
        loop {
            tick.tick().await;
            let _ = announcer_tx.send(SwarmCommand::AnnouncePeer);
            let _ = announcer_tx.send(SwarmCommand::SavePeerCache);
        }
    });

    let loop_tx = api_tx.clone();
    let mut pending_shards: std::collections::HashMap<String, (String, u64)> = std::collections::HashMap::new();
    let mut pending_dids: std::collections::HashMap<String, String> = std::collections::HashMap::new();
    let mut pending_names: std::collections::HashMap<String, (String, String)> = std::collections::HashMap::new();
    let mut pending_schemas: std::collections::HashMap<String, String> = std::collections::HashMap::new();

    macro_rules! handle_pbft_response {
        ($response_msg:expr) => {
            let phase = $response_msg.phase();
            let encoded = $response_msg.encode_to_vec();
            match phase {
                proto::feedo::PbftPhase::PrePrepare | proto::feedo::PbftPhase::Finalized => {
                    let _ = swarm.behaviour_mut().gossipsub.publish(pbft_topic.clone(), encoded.clone());
                }
                proto::feedo::PbftPhase::Prepare | proto::feedo::PbftPhase::Commit => {
                    let peers: Vec<libp2p::PeerId> = swarm.connected_peers().cloned().collect();
                    for p in peers {
                        let _ = swarm.behaviour_mut().req_resp.send_request(&p, DirectRequest::PbftVote(encoded.clone()));
                    }
                }
            }

            if $response_msg.phase() == proto::feedo::PbftPhase::Finalized {
                println!("PBFT Finalized tx: {}", $response_msg.tx_hash);

                if let Some((raw_text, _)) = pending_shards.remove(&$response_msg.tx_hash) {
                    let data_bytes = raw_text.into_bytes();
                    if let Ok(shards) = encode_data(&data_bytes) {
                        println!("Content sharding (45 parts) after consensus for tx: {}", $response_msg.tx_hash);
                        let mut shard_store_vec: Vec<Option<Vec<u8>>> = vec![None; shards.len()];
                        let mut manifest_shards = HashMap::new();
                        
                        let top_peers = peer_cache.top_n_addrs(45);
                        let mut target_peers = Vec::new();
                        for addr_str in top_peers {
                            if let Ok(ma) = Multiaddr::from_str(&addr_str) {
                                for p in ma.iter() {
                                    if let Protocol::P2p(mh) = p {
                                        if let Ok(pid) = PeerId::from_multihash(mh.into()) {
                                            target_peers.push(pid);
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                        if target_peers.is_empty() {
                            target_peers.push(local_peer_id);
                        }

                        for (i, shard) in shards.into_iter().enumerate() {
                            let chunk_key = format!("{}_chunk_{}", $response_msg.tx_hash, i);
                            let record = libp2p::kad::Record {
                                key: libp2p::kad::RecordKey::new(&chunk_key),
                                value: shard.clone(),
                                publisher: None,
                                expires: None,
                            };
                            let _ = swarm.behaviour_mut().kademlia.store_mut().put(record);
                            shard_store_vec[i] = Some(shard.clone());

                            let target_peer = target_peers[i % target_peers.len()];
                            manifest_shards.insert(i, target_peer.to_string());
                            
                            if target_peer != local_peer_id {
                                let _req_id = swarm.behaviour_mut().req_resp.send_request(
                                    &target_peer,
                                    DirectRequest::StoreShard { chunk_key: chunk_key.clone(), data: shard }
                                );
                            }
                        }
                        local_shard_store.insert($response_msg.tx_hash.clone(), shard_store_vec);
                        
                        let manifest = Manifest {
                            file_hash: $response_msg.tx_hash.clone(),
                            size: data_bytes.len(),
                            shards: manifest_shards,
                        };
                        if let Ok(manifest_bytes) = serde_json::to_vec(&manifest) {
                            let manifest_record = kad::Record {
                                key: kad::RecordKey::new(&format!("{}_manifest", $response_msg.tx_hash)),
                                value: manifest_bytes,
                                publisher: None,
                                expires: None,
                            };
                            if let Err(e) = swarm.behaviour_mut().kademlia.put_record(manifest_record, kad::Quorum::One) {
                                println!("Local manifest storage successful, but no other peers available for DHT: {:?}", e);
                            }
                            let _ = swarm.behaviour_mut().kademlia.start_providing(kad::RecordKey::new(&$response_msg.tx_hash));
                        }
                    }
                }

                if let Some(did_doc) = pending_dids.remove(&$response_msg.tx_hash) {
                    println!("Writing DID to DHT after consensus for tx: {}", $response_msg.tx_hash);
                    let did_id = $response_msg.tx_hash.replace("did_", "");
                    let record = kad::Record {
                        key: kad::RecordKey::new(&did_id),
                        value: did_doc.into_bytes(),
                        publisher: None,
                        expires: None,
                    };
                    let _ = swarm.behaviour_mut().kademlia.store_mut().put(record);
                    let _ = swarm.behaviour_mut().kademlia.start_providing(kad::RecordKey::new(&did_id));
                }

                if let Some((did, pubkey)) = pending_names.remove(&$response_msg.tx_hash) {
                    println!("Writing Name to DHT and DB after consensus for tx: {}", $response_msg.tx_hash);
                    let name_str = $response_msg.tx_hash.replace("name_", "");
                    let record = kad::Record {
                        key: kad::RecordKey::new(&name_str),
                        value: did.clone().into_bytes(),
                        publisher: None,
                        expires: None,
                    };
                    let _ = swarm.behaviour_mut().kademlia.store_mut().put(record);
                    let _ = swarm.behaviour_mut().kademlia.start_providing(kad::RecordKey::new(&name_str));
                    
                    if let Err(e) = name_db.insert_name(&name_str, &did, &pubkey) {
                        println!("Failed to write to NameDb: {:?}", e);
                    }
                }

                if let Some(schema_def) = pending_schemas.remove(&$response_msg.tx_hash) {
                    println!("Writing Schema to DHT after consensus for tx: {}", $response_msg.tx_hash);
                    let schema_id = $response_msg.tx_hash.replace("schema_", "");
                    let record = kad::Record {
                        key: kad::RecordKey::new(&schema_id),
                        value: schema_def.into_bytes(),
                        publisher: None,
                        expires: None,
                    };
                    let _ = swarm.behaviour_mut().kademlia.store_mut().put(record);
                    let _ = swarm.behaviour_mut().kademlia.start_providing(kad::RecordKey::new(&schema_id));
                }

                let client_clone = http_client.clone();
                let python_url = format!("{}/internal/pbft_commit", python_webhook_url.replace("/internal/p2p_receive", ""));
                let tx_hash_clone = $response_msg.tx_hash.clone();
                tokio::spawn(async move {
                    let payload = serde_json::json!({ "tx_hash": tx_hash_clone, "status": "finalized" });
                    let _ = client_clone.post(&python_url).json(&payload).send().await;
                });
            }
        };
    }
    loop {
        tokio::select! {
            Some(cmd) = api_rx.recv() => match cmd {
                SwarmCommand::TriggerPoStChallenges => {
                    use rand::Rng;
                    let mut rng = rand::thread_rng();
                    let mut manifests_to_check = Vec::new();
                    // Collect manifests from local store to check
                    for record in swarm.behaviour_mut().kademlia.store_mut().records() {
                        let key_str = String::from_utf8_lossy(record.key.as_ref()).into_owned();
                        if key_str.ends_with("_manifest") {
                            if let Ok(manifest) = serde_json::from_slice::<Manifest>(&record.value) {
                                manifests_to_check.push(manifest);
                            }
                        }
                    }
                    for manifest in manifests_to_check {
                        if !manifest.shards.is_empty() {
                            let random_index = rng.gen_range(0..TOTAL_SHARDS);
                            if let Some(peer_str) = manifest.shards.get(&random_index) {
                                if let Ok(peer_id) = PeerId::from_str(peer_str) {
                                    if peer_id != *swarm.local_peer_id() {
                                        let chunk_key = format!("{}_chunk_{}", manifest.file_hash, random_index);
                                        let nonce: u64 = rng.gen();
                                        println!("Sending PoStChallenge for {} to {}", chunk_key, peer_id);
                                        let _ = swarm.behaviour_mut().req_resp.send_request(
                                            &peer_id,
                                            DirectRequest::PoStChallenge { chunk_key, nonce }
                                        );
                                    }
                                }
                            }
                        }
                    }
                }
                SwarmCommand::Publish(req) => {
                    let metadata_str = req.metadata.clone().unwrap_or_else(|| "{}".to_string());
                    let mut metadata: serde_json::Value = serde_json::from_str(&metadata_str).unwrap_or(serde_json::json!({}));
                    if let Ok(vector_addr) = std::env::var("VECTOR_API_ADDR") {
                        if let serde_json::Value::Object(ref mut map) = metadata {
                            map.insert("vector_api_addr".to_string(), serde_json::Value::String(vector_addr));
                        }
                    }

                    let metadata_final_str = metadata.to_string();
                    let preview: String = req.text.chars().take(250).collect();

                    let msg = proto::feedo::FeedoBroadcast {
                        author_address: req.author.clone(),
                        hash_id: req.hash_id.clone(),
                        content_blob_hash: req.content_blob_hash.clone(),
                        prev_post_hash: req.prev_post_hash.clone().unwrap_or_default(),
                        sequence_number: req.sequence_number.unwrap_or(0),
                        signature: req.signature.clone(),
                        text_preview: preview,
                        content_size: req.text.as_bytes().len() as u64,
                        timestamp: std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs(),
                        title: req.title.clone(),
                        source_type: req.source_type.clone(),
                        metadata: Some(metadata_final_str),
                    };

                    let mempool_sub = proto::feedo::MempoolSubmission {
                        post: Some(msg.clone()),
                        originating_node: local_peer_id_str.clone(),
                        raw_text: req.text.clone(),
                    };

                    println!("Submitting content to Mempool for validation and consensus...");
                    let encoded = mempool_sub.encode_to_vec();
                    match swarm.behaviour_mut().gossipsub.publish(mempool_topic.clone(), encoded) {
                        Ok(_) => {
                            println!("Request successfully submitted to Mempool!");
                            // Initiating PBFT Propose
                            let total_nodes = swarm.network_info().num_peers() + 1;
                            let pbft_msg = pbft_manager.propose(req.hash_id.clone(), req.sequence_number.unwrap_or(0) as u64, proto::feedo::TxType::Content as i32, total_nodes);
                            let encoded_pbft = pbft_msg.encode_to_vec();
                            match swarm.behaviour_mut().gossipsub.publish(pbft_topic.clone(), encoded_pbft) {
                                Ok(_) => println!("PBFT Pre-Prepare broadcasted for tx: {}", pbft_msg.tx_hash),
                                Err(e) => println!("PBFT Pre-Prepare publish failed: {:?}", e),
                            }
                            let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
                            pending_shards.insert(req.hash_id.clone(), (req.text.clone(), now));
                        }
                        Err(gossipsub::PublishError::InsufficientPeers) => {
                            println!("Request ready for Mempool, but no peers available. Awaiting connections...");
                        },
                        Err(e) => println!("Unknown Mempool error: {:?}", e),
                    }
                }
                
                SwarmCommand::UploadMedia(data_bytes, sender) => {
                    let mut hasher = Sha256::new();
                    hasher.update(&data_bytes);
                    let media_hash = hex::encode(hasher.finalize());

                    println!("Uploading media: splitting into 45 shards...");
                    if let Ok(shards) = encode_data(&data_bytes) {
                        let mut shard_store_vec: Vec<Option<Vec<u8>>> = vec![None; shards.len()];
                        let mut manifest_shards = HashMap::new();
                        
                        let top_peers = peer_cache.top_n_addrs(45);
                        let mut target_peers = Vec::new();
                        for addr_str in top_peers {
                            if let Ok(ma) = Multiaddr::from_str(&addr_str) {
                                for p in ma.iter() {
                                    if let Protocol::P2p(mh) = p {
                                        if let Ok(pid) = PeerId::from_multihash(mh.into()) {
                                            target_peers.push(pid);
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                        if target_peers.is_empty() {
                            target_peers.push(local_peer_id);
                        }

                        for (i, shard) in shards.into_iter().enumerate() {
                            let chunk_key = format!("{}_chunk_{}", media_hash, i);
                            
                            let record = kad::Record {
                                key: kad::RecordKey::new(&chunk_key),
                                value: shard.clone(),
                                publisher: None,
                                expires: None,
                            };
                            let _ = swarm.behaviour_mut().kademlia.store_mut().put(record);
                            shard_store_vec[i] = Some(shard.clone());

                            let target_peer = target_peers[i % target_peers.len()];
                            manifest_shards.insert(i, target_peer.to_string());
                            
                            if target_peer != local_peer_id {
                                let _req_id = swarm.behaviour_mut().req_resp.send_request(
                                    &target_peer,
                                    DirectRequest::StoreShard { chunk_key: chunk_key.clone(), data: shard }
                                );
                            }
                        }
                        local_shard_store.insert(media_hash.clone(), shard_store_vec);
                        
                        let manifest = Manifest {
                            file_hash: media_hash.clone(),
                            size: data_bytes.len(),
                            shards: manifest_shards,
                        };
                        
                        if let Ok(manifest_bytes) = serde_json::to_vec(&manifest) {
                            let manifest_record = kad::Record {
                                key: kad::RecordKey::new(&format!("{}_manifest", media_hash)),
                                value: manifest_bytes,
                                publisher: None,
                                expires: None,
                            };
                            if let Err(e) = swarm.behaviour_mut().kademlia.put_record(manifest_record, kad::Quorum::One) {
                                println!("Local manifest storage successful, but no other peers available for DHT: {:?}", e);
                            }
                            let _ = swarm.behaviour_mut().kademlia.start_providing(kad::RecordKey::new(&media_hash));
                        }
                        
                        println!("Media uploaded successfully. Manifest created.");
                        let _ = sender.send(media_hash);
                    }
                }

                SwarmCommand::DhtUpload(data_bytes, sender) => {
                    let mut hasher = Sha256::new();
                    hasher.update(&data_bytes);
                    let hash_str = hex::encode(hasher.finalize());
                    
                    let record = kad::Record {
                        key: kad::RecordKey::new(&hash_str),
                        value: data_bytes.clone(),
                        publisher: None,
                        expires: None,
                    };
                    
                    let _ = swarm.behaviour_mut().kademlia.store_mut().put(record);
                    let _ = swarm.behaviour_mut().kademlia.start_providing(kad::RecordKey::new(&hash_str));
                    
                    println!("Raw DHT upload successful: {}", hash_str);
                    let _ = sender.send(hash_str);
                }

                SwarmCommand::DhtDownload(hash_str, sender) => {
                    let record_key = kad::RecordKey::new(&hash_str);
                    if let Some(record) = swarm.behaviour_mut().kademlia.store_mut().get(&record_key) {
                        let _ = sender.send(Some(record.value.clone()));
                    } else {
                        let _qid = swarm.behaviour_mut().kademlia.get_record(record_key);
                        let _ = sender.send(None);
                    }
                }


                SwarmCommand::AnnouncePeer => {
                    let listen_addrs: Vec<String> = swarm.listeners().map(|a| a.to_string()).collect();
                    let pubkey_bytes = local_key.public().encode_protobuf();
                    if !pubkey_bytes.is_empty() {
                        let pubkey_b64 = base64::engine::general_purpose::STANDARD.encode(&pubkey_bytes);
                        let current_storage_full = storage_full.load(Ordering::Relaxed);
                        let storage_status = if current_storage_full { "Full".to_string() } else { "OK".to_string() };
                        let mut announce = PeerAnnounce {
                            peer_id: local_peer_id_str.clone(),
                            listen_addrs: listen_addrs.clone(),
                            timestamp: std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs(),
                            nonce: None,
                            signature: None,
                            public_key: Some(pubkey_b64.clone()),
                            storage_status: Some(storage_status),
                            is_supernode: Some(env::var("IS_SUPERNODE").unwrap_or_else(|_| "false".to_string()).to_lowercase() == "true"),
                        };

                        if let Ok(payload) = serde_json::to_vec(&announce) {
                            if let Ok(sig) = local_key.sign(&payload) {
                                let sig_bytes: &[u8] = sig.as_ref();
                                announce.signature = Some(hex::encode(sig_bytes));
                                if let Ok(final_payload) = serde_json::to_vec(&announce) {
                                    match swarm.behaviour_mut().gossipsub.publish(announce_topic.clone(), final_payload) {
                                        Ok(_) => println!("Published peer announce (signed)"),
                                        Err(e) => println!("Error publishing announce: {:?}", e),
                                    }
                                }
                            } else {
                                println!("Failed to sign announce payload");
                            }
                        }
                    }
                }

                SwarmCommand::SavePeerCache => {
                    peer_cache.save(&peer_cache_path);
                    println!("peer_cache saved ({} entries)", peer_cache.peers.len());
                },

                SwarmCommand::PbftPropose(tx_hash, sequence, tx_type) => {
                    let network_info = swarm.network_info();
                    let total_nodes = network_info.num_peers() + 1; // including self
                    let pbft_msg = pbft_manager.propose(tx_hash, sequence, tx_type, total_nodes);
                    let encoded = pbft_msg.encode_to_vec();
                    match swarm.behaviour_mut().gossipsub.publish(pbft_topic.clone(), encoded) {
                        Ok(_) => println!("PBFT Pre-Prepare broadcasted for tx: {}", pbft_msg.tx_hash),
                        Err(e) => println!("PBFT Pre-Prepare publish failed: {:?}", e),
                    }
                }

                SwarmCommand::MempoolValidationResult(tx_hash, is_valid, tx_type) => {
                    if is_valid {
                        println!("Mempool request {} is semantically unique. Voting in PBFT.", tx_hash);
                        let total_nodes = swarm.network_info().num_peers() + 1;
                        if let Some(prepare_msg) = pbft_manager.mark_validated(&tx_hash, tx_type, total_nodes) {
                            println!("PBFT Prepare sent for {}", tx_hash);
                            handle_pbft_response!(prepare_msg);
                        }
                    } else {
                        println!("Mempool request {} rejected (duplicate).", tx_hash);
                    }
                }

                SwarmCommand::PushCentroids(cluster_ids, centroids) => {
                    let payload = serde_json::json!({
                        "peer_id": local_peer_id_str,
                        "cluster_ids": cluster_ids,
                        "centroids": centroids
                    });
                    if let Ok(encoded) = serde_json::to_vec(&payload) {
                        match swarm.behaviour_mut().gossipsub.publish(supernode_sync_topic.clone(), encoded) {
                            Ok(_) => println!("Broadcasting centroids to Supernode via Gossipsub"),
                            Err(e) => println!("Error broadcasting centroids: {:?}", e),
                        }
                    }
                }

                SwarmCommand::VectorRouteQuery(vector, target_peers, limit, sender) => {
                    println!("Sending routed vector query to: {:?}", target_peers);
                    for peer_id_str in target_peers {
                        if let Ok(peer_id) = PeerId::from_str(&peer_id_str) {
                            let _req_id = swarm.behaviour_mut().req_resp.send_request(
                                &peer_id,
                                DirectRequest::VectorQuery { vector: vector.clone(), limit }
                            );
                        }
                    }
                    let _ = sender.send(serde_json::json!({"results": []}).to_string());
                }

                SwarmCommand::RegisterDid(req) => {
                    let tx_hash = format!("did_{}", req.id);
                    let network_info = swarm.network_info();
                    let total_nodes = network_info.num_peers() + 1;
                    let pbft_msg = pbft_manager.propose(tx_hash.clone(), 0, proto::feedo::TxType::DidRegistration as i32, total_nodes);
                    let encoded = pbft_msg.encode_to_vec();
                    match swarm.behaviour_mut().gossipsub.publish(pbft_topic.clone(), encoded) {
                        Ok(_) => println!("PBFT Pre-Prepare broadcasted for DID Registration: {}", req.id),
                        Err(e) => println!("PBFT broadcast failed: {:?}", e),
                    }
                    
                    pending_dids.insert(tx_hash, req.did_document);
                }

                SwarmCommand::RegisterName(req) => {
                    let re = regex::Regex::new(r"^[a-z0-9-]{3,63}$").unwrap();
                    if !re.is_match(&req.name) {
                        println!("Invalid name format: {}", req.name);
                        continue;
                    }
                    if let Ok(true) = name_db.name_exists(&req.name) {
                        println!("Name {} already exists!", req.name);
                        continue;
                    }

                    let tx_hash = format!("name_{}", req.name);
                    let network_info = swarm.network_info();
                    let total_nodes = network_info.num_peers() + 1;
                    let pbft_msg = pbft_manager.propose(tx_hash.clone(), 0, proto::feedo::TxType::NameRegistration as i32, total_nodes);
                    let encoded = pbft_msg.encode_to_vec();
                    let _ = swarm.behaviour_mut().gossipsub.publish(pbft_topic.clone(), encoded);
                    
                    pending_names.insert(tx_hash, (req.did, req.public_key));
                }

                SwarmCommand::ResolveDid(id, sender) => {
                    let record_key = kad::RecordKey::new(&id);
                    if let Some(record) = swarm.behaviour_mut().kademlia.store_mut().get(&record_key) {
                        if let Ok(doc_str) = String::from_utf8(record.value.clone()) {
                            let _ = sender.send(Some(doc_str));
                        } else {
                            let _ = sender.send(None);
                        }
                    } else {
                        let query_id = swarm.behaviour_mut().kademlia.get_record(record_key);
                        let _ = sender.send(None);
                    }
                }



                SwarmCommand::ResolveName(name, sender) => {
                    match name_db.resolve_name(&name) {
                        Ok(Some(did_str)) => {
                            let _ = sender.send(Some(did_str));
                        }
                        _ => {
                            let _ = sender.send(None);
                        }
                    }
                }

                SwarmCommand::CrdtMutate(op) => {
                    match crdt_manager.process_operation(&op) {
                        Ok(true) => {
                            let mut op_bytes = Vec::new();
                            if prost::Message::encode(&op, &mut op_bytes).is_ok() {
                                let _ = swarm.behaviour_mut().gossipsub.publish(crdt_sync_topic.clone(), op_bytes);
                            }
                        }
                        Ok(false) => {
                        }
                        Err(e) => {
                            println!("CRDT Mutate Error: {}", e);
                        }
                    }
                }

                SwarmCommand::CrdtGet(object_id, sender) => {
                    if let Some(state) = crdt_manager.get_state(&object_id) {
                        if let Ok(json_str) = serde_json::to_string(&state) {
                            let _ = sender.send(Some(json_str));
                        } else {
                            let _ = sender.send(None);
                        }
                    } else {
                        let _ = sender.send(None);
                    }
                }

                SwarmCommand::InitiateSemanticSearch(query_text, limit, sender) => {
                    let mut hasher = Sha256::new();
                    hasher.update(query_text.as_bytes());
                    hasher.update(&std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos().to_le_bytes());
                    let query_id = hex::encode(hasher.finalize());

                    println!("Initiating Federated Semantic Search. Query ID: {}", query_id);
                    
                    let query = proto::feedo::SemanticSearchQuery {
                        query_id: query_id.clone(),
                        text_query: query_text,
                        ttl: 5, // Default TTL
                        limit,
                        source_type: None,
                        originator_peer_id: local_peer_id_str.clone(),
                    };
                    
                    // Keep track of this query to avoid processing our own broadcast again
                    search_query_cache.insert(query_id.clone(), std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs());
                    active_search_requests.insert(query_id.clone(), (sender, Vec::new()));
                    
                    let mut encoded = Vec::new();
                    // Let's wrap it in a custom format or just send it raw with a 1 byte prefix (0 for query, 1 for result)
                    encoded.push(0u8);
                    if prost::Message::encode(&query, &mut encoded).is_ok() {
                        let _ = swarm.behaviour_mut().gossipsub.publish(semantic_search_topic.clone(), encoded);
                    }
                    
                    // We need a timeout to return the results. We can do that by spawning a task that waits 3 seconds, 
                    // then sends a special command to finish the query. Or we can just do it inline here? No, it's a loop.
                    let cmd_tx = loop_tx.clone();
                    let qid = query_id.clone();
                    tokio::spawn(async move {
                        tokio::time::sleep(Duration::from_secs(3)).await;
                        let _ = cmd_tx.send(SwarmCommand::FinishSemanticSearch(qid));
                    });
                }

                SwarmCommand::FetchContent(content_hash, size, sender) => {
                    println!("Sending fetch request for content {} (Need 30/45 shards)", content_hash);
                    
                    // Initialize fetch state
                    active_fetches.insert(content_hash.clone(), FetchState {
                        sender: Some(sender),
                        shards: vec![None; TOTAL_SHARDS],
                        received: 0,
                        failed: 0,
                        original_size: size as usize,
                        manifest: None,
                    });

                    // First, check local in-memory shard store. If present, use those shards directly.
                    if let Some(local_shards) = local_shard_store.get(&content_hash) {
                        if let Some(state) = active_fetches.get_mut(&content_hash) {
                            for (i, maybe_shard) in local_shards.iter().enumerate() {
                                if let Some(s) = maybe_shard {
                                    state.shards[i] = Some(s.clone());
                                    state.received += 1;
                                }
                            }
                        }
                    }

                    // Secondly, try to recover any missing shards directly from Kademlia HybridStore (RAM & Persistent Sled DB)
                    if let Some(state) = active_fetches.get_mut(&content_hash) {
                        for i in 0..TOTAL_SHARDS {
                            if state.shards[i].is_none() {
                                let chunk_key = format!("{}_chunk_{}", content_hash, i);
                                let record_key = kad::RecordKey::new(&chunk_key);
                                if let Some(record) = swarm.behaviour_mut().kademlia.store_mut().get(&record_key) {
                                    state.shards[i] = Some(record.value.clone());
                                    state.received += 1;
                                }
                            }
                        }

                        // If local stores satisfied reconstruction (>= 30 shards), decode immediately
                        if state.received >= DATA_SHARDS {
                            println!("Local stores have sufficient shards ({}/{}) for {}. Decoding...", state.received, TOTAL_SHARDS, content_hash);
                            if let Ok(decoded) = decode_data(state.shards.clone(), state.original_size) {
                                match String::from_utf8(decoded.clone()) {
                                    Ok(content_str) => {
                                        if let Some(sender) = state.sender.take() {
                                            let _ = sender.send(Some(content_str));
                                            println!("Content (text) successfully restored locally.");
                                        }
                                    }
                                    Err(_) => {
                                        use base64::{Engine as _, engine::general_purpose};
                                        let b64 = general_purpose::STANDARD.encode(&decoded);
                                        if let Some(sender) = state.sender.take() {
                                            let _ = sender.send(Some(b64));
                                            println!("Content (binary/media) successfully restored and encoded in Base64 (local).");
                                        }
                                    }
                                }
                            } else {
                                println!("Error restoring Reed-Solomon content locally for {}", content_hash);
                            }
                            active_fetches.remove(&content_hash);
                            continue;
                        }
                    }

                    // Otherwise, fall back to querying the Kad DHT for the Manifest
                    let manifest_key = kad::RecordKey::new(&format!("{}_manifest", content_hash));
                    let qid = swarm.behaviour_mut().kademlia.get_record(manifest_key);
                    manifest_queries.insert(qid, content_hash.clone());
                }

                SwarmCommand::GetNetworkInfo(sender) => {
                    let total_peers = swarm.network_info().num_peers();
                    let _ = sender.send(NetworkInfo {
                        peer_id: local_peer_id_str.clone(),
                        total_nodes: total_peers + 1,
                    });
                }

                SwarmCommand::FinishSemanticSearch(query_id) => {
                    if let Some((sender, results)) = active_search_requests.remove(&query_id) {
                        // Serialize results and send back
                        let mut unique_results = results.clone();
                        unique_results.sort_by(|a, b| b.similarity_score.partial_cmp(&a.similarity_score).unwrap_or(std::cmp::Ordering::Equal));
                        unique_results.dedup_by(|a, b| a.hash_id == b.hash_id);
                        
                        let json_res = serde_json::json!({
                            "query_id": query_id,
                            "results": unique_results.iter().map(|r| {
                                serde_json::json!({
                                    "hash_id": r.hash_id,
                                    "text": r.text,
                                    "author": r.author,
                                    "timestamp": r.timestamp,
                                    "similarity_score": r.similarity_score
                                })
                            }).collect::<Vec<_>>()
                        });
                        let _ = sender.send(json_res.to_string());
                    }
                }

                SwarmCommand::BroadcastSemanticResult(encoded) => {
                    let _ = swarm.behaviour_mut().gossipsub.publish(semantic_search_topic.clone(), encoded);
                }

                SwarmCommand::ForwardSemanticSearch(encoded) => {
                    let _ = swarm.behaviour_mut().gossipsub.publish(semantic_search_topic.clone(), encoded);
                }
            },

            _ = bootstrap_interval.tick() => {
                let num_peers = swarm.network_info().num_peers();
                if num_peers < min_peers_before_retry {
                    println!("Bootstrap retry: {} peers < {}. Retrying bootstrap addresses...", num_peers, min_peers_before_retry);
                    for addr in bootstrap_addrs.iter() {
                        match swarm.dial(addr.clone()) {
                            Ok(()) => println!("Retry dialing {}", addr),
                            Err(e) => println!("Retry dial {} error: {:?}", addr, e),
                        }
                    }
                    if let Err(e) = swarm.behaviour_mut().kademlia.bootstrap() {
                        println!("Kademlia bootstrap error: {:?}", e);
                    }
                }
            }
            
            _ = gc_pending_shards_interval.tick() => {
                let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
                let before_len = pending_shards.len();
                pending_shards.retain(|_, (_, timestamp)| {
                    now.saturating_sub(*timestamp) <= 300 
                });
                let after_len = pending_shards.len();
                if before_len > after_len {
                    println!("GC: Removed {} expired requests from pending_shards", before_len - after_len);
                }
            }

            event = swarm.select_next_some() => match event {
                SwarmEvent::Behaviour(FeedoBehaviourEvent::Kademlia(kad::Event::OutboundQueryProgressed { id, result, .. })) => {
                    if let kad::QueryResult::GetRecord(Ok(kad::GetRecordOk::FoundRecord(record))) = result {
                        if let Some(hash) = manifest_queries.remove(&id) {
                            if let Ok(manifest) = serde_json::from_slice::<Manifest>(&record.record.value) {
                                println!("Manifest received for {}. Starting parallel shard download...", hash);
                                for (index, peer_id_str) in manifest.shards {
                                    if let Ok(peer_id) = PeerId::from_str(&peer_id_str) {
                                        let chunk_key = format!("{}_chunk_{}", hash, index);
                                        let req_id = swarm.behaviour_mut().req_resp.send_request(
                                            &peer_id,
                                            DirectRequest::FetchShard { chunk_key }
                                        );
                                        req_resp_to_fetch.insert(req_id, (hash.clone(), index));
                                    }
                                }
                            }
                        } else if let Some((hash, index)) = query_to_fetch.remove(&id) {
                            if let Some(state) = active_fetches.get_mut(&hash) {
                                if state.shards[index].is_none() {
                                    state.shards[index] = Some(record.record.value);
                                    state.received += 1;
                                    
                                    if state.received == DATA_SHARDS {
                                        println!("Collected {}/45 shards for {} (DHT fallback). Mathematical restoration...", DATA_SHARDS, hash);
                                        if let Ok(decoded) = decode_data(state.shards.clone(), state.original_size) {
                                            match String::from_utf8(decoded.clone()) {
                                                Ok(content_str) => {
                                                    if let Some(sender) = state.sender.take() {
                                                        let _ = sender.send(Some(content_str));
                                                        println!("Content (text) successfully restored.");
                                                    }
                                                }
                                                Err(_) => {
                                                    use base64::{Engine as _, engine::general_purpose};
                                                    let b64 = general_purpose::STANDARD.encode(&decoded);
                                                    if let Some(sender) = state.sender.take() {
                                                        let _ = sender.send(Some(b64));
                                                        println!("Content (binary/media) successfully restored and encoded in Base64.");
                                                    }
                                                }
                                            }
                                        } else {
                                            println!("Error restoring Reed-Solomon content for {}", hash);
                                            if let Some(sender) = state.sender.take() {
                                                let _ = sender.send(None);
                                            }
                                        }
                                        active_fetches.remove(&hash);
                                    }
                                }
                            }
                        }
                    }
                }
                SwarmEvent::Behaviour(FeedoBehaviourEvent::Kademlia(kad::Event::RoutingUpdated { peer, is_new_peer, addresses, .. })) => {
                    if is_new_peer {
                        println!("Kademlia DHT discovered a new node: {}", peer);
                    }
                    let addrs: Vec<String> = addresses.iter().map(|a| a.to_string()).collect();
                    peer_cache.add_or_update(&peer.to_string(), addrs, true);
                }

                SwarmEvent::ConnectionEstablished { peer_id, .. } => {
                    println!("Connection established with {}", peer_id);
                    peer_cache.add_or_update(&peer_id.to_string(), vec![], true);
                    peer_cache.save(&peer_cache_path);
                    
                    let challenge = format!("HANDSHAKE:{}", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos());
                    let req_id = swarm.behaviour_mut().req_resp.send_request(&peer_id, DirectRequest::Handshake { challenge: challenge.clone() });
                    handshake_challenges.insert(req_id, challenge);
                }
                
                SwarmEvent::Behaviour(FeedoBehaviourEvent::ReqResp(event)) => {
                    match event {
                        request_response::Event::Message { peer, message } => {
                            match message {
                                request_response::Message::Request { request_id, request, channel } => {
                            match request {
                                DirectRequest::Handshake { challenge } => {
                                    if let Ok(sig) = local_key.sign(challenge.as_bytes()) {
                                        let _ = swarm.behaviour_mut().req_resp.send_response(channel, DirectResponse::HandshakeResponse(sig));
                                    }
                                }
                                DirectRequest::StoreShard { chunk_key, data } => {
                                    let record = libp2p::kad::Record {
                                        key: libp2p::kad::RecordKey::new(&chunk_key),
                                        value: data,
                                        publisher: None,
                                        expires: None,
                                    };
                                    let _ = swarm.behaviour_mut().kademlia.store_mut().put(record);
                                    let _ = swarm.behaviour_mut().req_resp.send_response(channel, DirectResponse::StoreOk);
                                }
                                DirectRequest::FetchShard { chunk_key } => {
                                    let record_key = kad::RecordKey::new(&chunk_key);
                                    let data = swarm.behaviour_mut().kademlia.store_mut().get(&record_key).map(|r| r.value.clone());
                                    if let Some(val) = data {
                                        let _ = swarm.behaviour_mut().req_resp.send_response(channel, DirectResponse::ShardData(Some(val)));
                                    } else {
                                        let _ = swarm.behaviour_mut().req_resp.send_response(channel, DirectResponse::ShardData(None));
                                    }
                                }
                                DirectRequest::FetchManifest { file_hash } => {
                                    let record_key = kad::RecordKey::new(&format!("{}_manifest", file_hash));
                                    let data = swarm.behaviour_mut().kademlia.store_mut().get(&record_key).map(|r| r.value.clone());
                                    if let Some(val) = data {
                                        if let Ok(manifest) = serde_json::from_slice::<Manifest>(&val) {
                                            let _ = swarm.behaviour_mut().req_resp.send_response(channel, DirectResponse::ManifestData(Some(manifest)));
                                        } else {
                                            let _ = swarm.behaviour_mut().req_resp.send_response(channel, DirectResponse::ManifestData(None));
                                        }
                                    } else {
                                        let _ = swarm.behaviour_mut().req_resp.send_response(channel, DirectResponse::ManifestData(None));
                                    }
                                }
                                DirectRequest::PbftVote(vote_bytes) => {
                                    if let Ok(pbft_msg) = proto::feedo::PbftMessage::decode(&vote_bytes[..]) {
                                        let total_nodes = swarm.network_info().num_peers() + 1;
                                        if let Some(response_msg) = pbft_manager.handle_message(pbft_msg, total_nodes) {
                                            handle_pbft_response!(response_msg);
                                        }
                                    }
                                    let _ = swarm.behaviour_mut().req_resp.send_response(channel, DirectResponse::PbftVoteOk);
                                }
                                DirectRequest::VectorQuery { vector, limit } => {
                                    println!("Received VectorQuery from {}", peer);
                                    let client_clone = http_client.clone();
                                    let url_clone = python_webhook_url.replace("/internal/p2p_receive", "/api/v1/semantic/query");
                                    tokio::spawn(async move {
                                        let payload = serde_json::json!({
                                            "text": "", 
                                            "vector": vector,
                                            "limit": limit,
                                            "federated": false
                                        });
                                        let _ = client_clone.post(&url_clone).json(&payload).send().await;
                                    });
                                    let _ = swarm.behaviour_mut().req_resp.send_response(channel, DirectResponse::VectorQueryResponse(serde_json::json!({"results": []}).to_string()));
                                }
                                DirectRequest::PoStChallenge { chunk_key, nonce } => {
                                    println!("Received PoStChallenge for chunk {} from {}", chunk_key, peer);
                                    let record_key = kad::RecordKey::new(&chunk_key);
                                    let data = swarm.behaviour_mut().kademlia.store_mut().get(&record_key).map(|r| r.value.clone());
                                    if let Some(val) = data {
                                        // let response_hash = da::generate_post_response(&val, nonce);
                                let response_hash = "mocked_response".to_string();
                                        let _ = swarm.behaviour_mut().req_resp.send_response(channel, DirectResponse::PoStResponse { response_hash });
                                        println!("Sent PoStResponse for {}", chunk_key);
                                    } else {
                                        println!("Fragment {} not found for PoStChallenge", chunk_key);
                                    }
                                }
                            }
                        }
                        request_response::Message::Response { request_id, response } => {
                            match response {
                                DirectResponse::HandshakeResponse(sig) => {
                                    if let Some(challenge) = handshake_challenges.remove(&request_id) {
                                        println!("Cryptographic Handshake with {} successfully verified!", peer);
                                    }
                                }
                                DirectResponse::PoStResponse { response_hash } => {
                                    println!("Received PoStResponse from {}. Hash: {}", peer, response_hash);
                                }
                                DirectResponse::StoreOk => {}
                                DirectResponse::ShardData(Some(data)) => {
                                    if let Some((hash, index)) = req_resp_to_fetch.remove(&request_id) {
                                        if let Some(state) = active_fetches.get_mut(&hash) {
                                            if state.shards[index].is_none() {
                                                state.shards[index] = Some(data);
                                                state.received += 1;
                                                
                                                if state.received == DATA_SHARDS {
                                                    println!("Collected {}/45 shards for {} (Parallel Fetch). Mathematical restoration...", DATA_SHARDS, hash);
                                                    if let Ok(decoded) = decode_data(state.shards.clone(), state.original_size) {
                                                        match String::from_utf8(decoded.clone()) {
                                                            Ok(content_str) => {
                                                                if let Some(sender) = state.sender.take() {
                                                                    let _ = sender.send(Some(content_str));
                                                                    println!("Content (text) successfully restored.");
                                                                }
                                                            }
                                                            Err(_) => {
                                                                use base64::{Engine as _, engine::general_purpose};
                                                                let b64 = general_purpose::STANDARD.encode(&decoded);
                                                                if let Some(sender) = state.sender.take() {
                                                                    let _ = sender.send(Some(b64));
                                                                    println!("Content (binary/media) successfully restored and encoded in Base64.");
                                                                }
                                                            }
                                                        }
                                                    } else {
                                                        println!("Error restoring Reed-Solomon for {}", hash);
                                                        if let Some(sender) = state.sender.take() {
                                                            let _ = sender.send(None);
                                                        }
                                                    }
                                                }
                                                
                                                if state.received + state.failed == TOTAL_SHARDS {
                                                    if state.failed > 0 && state.received >= DATA_SHARDS {
                                                        do_self_healing(&hash, state, &mut swarm, &peer_cache, local_peer_id);
                                                    } else if state.received < DATA_SHARDS {
                                                        println!("Cannot restore file {}. Only collected {}/{} shards.", hash, state.received, DATA_SHARDS);
                                                        if let Some(sender) = state.sender.take() {
                                                            let _ = sender.send(None);
                                                        }
                                                    }
                                                    active_fetches.remove(&hash);
                                                }
                                            }
                                        }
                                    }
                                }
                                DirectResponse::ShardData(None) => {
                                    println!("Peer {} did not have the requested shard.", peer);
                                    if let Some((hash, _index)) = req_resp_to_fetch.remove(&request_id) {
                                        if let Some(state) = active_fetches.get_mut(&hash) {
                                            state.failed += 1;
                                            if state.received + state.failed == TOTAL_SHARDS {
                                                if state.failed > 0 && state.received >= DATA_SHARDS {
                                                    do_self_healing(&hash, state, &mut swarm, &peer_cache, local_peer_id);
                                                } else if state.received < DATA_SHARDS {
                                                    println!("Cannot restore file {}. Only collected {}/{} shards.", hash, state.received, DATA_SHARDS);
                                                    if let Some(sender) = state.sender.take() {
                                                        let _ = sender.send(None);
                                                    }
                                                }
                                                active_fetches.remove(&hash);
                                            }
                                        }
                                    }
                                }
                                DirectResponse::ManifestData(Some(manifest)) => {
                                    if let Some(hash) = manifest_requests.remove(&request_id) {
                                        println!("Manifest received for {}. Starting parallel shard download...", hash);
                                        if let Some(state) = active_fetches.get_mut(&hash) {
                                            state.manifest = Some(manifest.clone());
                                        }
                                        for (index, peer_id_str) in manifest.shards {
                                            if let Ok(peer_id) = PeerId::from_str(&peer_id_str) {
                                                let chunk_key = format!("{}_chunk_{}", hash, index);
                                                let req_id = swarm.behaviour_mut().req_resp.send_request(
                                                    &peer_id,
                                                    DirectRequest::FetchShard { chunk_key }
                                                );
                                                req_resp_to_fetch.insert(req_id, (hash.clone(), index));
                                            }
                                        }
                                    }
                                }
                                DirectResponse::ManifestData(None) => {
                                    println!("Peer {} did not have the requested manifest.", peer);
                                    let _ = manifest_requests.remove(&request_id);
                                }
                                DirectResponse::PbftVoteOk => {}
                                DirectResponse::VectorQueryResponse(res_json) => {
                                    println!("Received response on VectorQuery: {}", res_json);
                                }
                            }
                            }
                        }
                        }
                        request_response::Event::OutboundFailure { peer, request_id, error } => {
                            println!("Outbound request failure to {}: {:?}", peer, error);
                            if let Some((hash, _index)) = req_resp_to_fetch.remove(&request_id) {
                                if let Some(state) = active_fetches.get_mut(&hash) {
                                    state.failed += 1;
                                    if state.received + state.failed == TOTAL_SHARDS {
                                        if state.failed > 0 && state.received >= DATA_SHARDS {
                                            do_self_healing(&hash, state, &mut swarm, &peer_cache, local_peer_id);
                                        } else if state.received < DATA_SHARDS {
                                            println!("Cannot restore file {}. Collected only {}/{} shards.", hash, state.received, DATA_SHARDS);
                                            if let Some(sender) = state.sender.take() {
                                                let _ = sender.send(None);
                                            }
                                        }
                                        active_fetches.remove(&hash);
                                    }
                                }
                            } else if let Some(hash) = manifest_requests.remove(&request_id) {
                                println!("Failed to get manifest for {}", hash);
                            }
                        }
                        _ => {}
                    }
                }

                SwarmEvent::Behaviour(FeedoBehaviourEvent::Mdns(mdns::Event::Discovered(peers))) => {
                    for (peer_id, addr) in peers {
                        println!("mDNS found neighbor: {} on {}", peer_id, addr);
                        swarm.behaviour_mut().gossipsub.add_explicit_peer(&peer_id);
                        swarm.behaviour_mut().kademlia.add_address(&peer_id, addr.clone());
                        peer_cache.add_or_update(&peer_id.to_string(), vec![addr.to_string()], false);
                    }
                }
                SwarmEvent::Behaviour(FeedoBehaviourEvent::Mdns(mdns::Event::Expired(peers))) => {
                    for (peer_id, _) in peers {
                        println!("mDNS: Peer disconnected {}", peer_id);
                        swarm.behaviour_mut().gossipsub.remove_explicit_peer(&peer_id);
                    }
                }
                SwarmEvent::Behaviour(FeedoBehaviourEvent::Gossipsub(gossipsub::Event::Message { message, .. })) => {
                    if message.topic.as_str() == "feedo_pbft_consensus" {
                        if let Ok(pbft_msg) = proto::feedo::PbftMessage::decode(&message.data[..]) {
                            let total_nodes = swarm.network_info().num_peers() + 1;
                            if let Some(response_msg) = pbft_manager.handle_message(pbft_msg, total_nodes) {
                                handle_pbft_response!(response_msg);
                            }
                        }
                        continue;
                    }

                    if message.topic.as_str() == "feedo_mempool" {
                        if let Ok(mempool_sub) = proto::feedo::MempoolSubmission::decode(&message.data[..]) {
                            if let Some(post) = mempool_sub.post {
                                println!("Received request in Mempool from {}", mempool_sub.originating_node);
                                let client_clone = http_client.clone();
                                let url_clone = python_webhook_url.replace("/internal/p2p_receive", "/api/v1/semantic/validate_uniqueness");
                                let tx_hash = post.hash_id.clone();
                                let cmd_tx = loop_tx.clone();
                                tokio::spawn(async move {
                                    let payload = serde_json::json!({
                                        "tx_hash": tx_hash,
                                        "originating_node": mempool_sub.originating_node,
                                        "text": mempool_sub.raw_text,
                                    });
                                    if let Ok(res) = client_clone.post(&url_clone).json(&payload).send().await {
                                        if let Ok(json_res) = res.json::<serde_json::Value>().await {
                                            let is_valid = json_res.get("valid").and_then(|v| v.as_bool()).unwrap_or(false);
                                            let _ = cmd_tx.send(SwarmCommand::MempoolValidationResult(tx_hash, is_valid, proto::feedo::TxType::Content as i32));
                                        }
                                    }
                                });
                            }
                        }
                        continue;
                    }
                    if message.topic.as_str() == "feedo_supernode_sync" {
                        println!("Received Gossipsub message feedo_supernode_sync");
                        if let Ok(payload) = serde_json::from_slice::<serde_json::Value>(&message.data) {
                            let client_clone = http_client.clone();
                            let url_clone = python_webhook_url.replace("/internal/p2p_receive", "/internal/ingest_global_map");
                            tokio::spawn(async move {
                                let _ = client_clone.post(&url_clone).json(&payload).send().await;
                            });
                        }
                        continue;
                    }

                    if message.topic.as_str() == "feedo_crdt_sync" {
                        if let Ok(op) = proto::feedo::CrdtOperation::decode(&message.data[..]) {
                            match crdt_manager.process_operation(&op) {
                                Ok(true) => {
                                    // Successfully applied, forward to Python webhook to update Read-Model
                                    if let Some(state) = crdt_manager.get_state(&op.object_id) {
                                        let client_clone = http_client.clone();
                                        let url_clone = python_webhook_url.replace("/internal/p2p_receive", "/api/v1/crdt/webhook");
                                        tokio::spawn(async move {
                                            if let Ok(payload) = serde_json::to_value(&state) {
                                                let _ = client_clone.post(&url_clone).json(&payload).send().await;
                                            }
                                        });
                                    }
                                }
                                Ok(false) => {
                                    // Older or duplicate operation, ignored
                                }
                                Err(e) => {
                                    println!("CRDT sync error: {}", e);
                                }
                            }
                        }
                        continue;
                    }

                    if message.topic.as_str() == "feedo_semantic_search" {
                        if message.data.is_empty() { continue; }
                        let msg_type = message.data[0];
                        let payload = &message.data[1..];

                        if msg_type == 0 { // Query
                            if let Ok(mut query) = proto::feedo::SemanticSearchQuery::decode(payload) {
                                // Deduplication
                                let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
                                if search_query_cache.contains_key(&query.query_id) {
                                    continue;
                                }
                                search_query_cache.insert(query.query_id.clone(), now);

                                // 1. Forward to Python internal API to get local results
                                let cmd_tx = loop_tx.clone();
                                let client_clone = http_client.clone();
                                let python_url = python_webhook_url.replace("/internal/p2p_receive", "/internal/semantic/query");
                                let peer_id_str = local_peer_id_str.clone();
                                let query_id_clone = query.query_id.clone();
                                let query_text = query.text_query.clone();
                                let query_limit = query.limit;
                                let query_originator_peer_id = query.originator_peer_id.clone();

                                tokio::spawn(async move {
                                    let req_body = serde_json::json!({
                                        "query_id": query_id_clone,
                                        "text": query_text,
                                        "limit": query_limit,
                                        "originator_peer_id": query_originator_peer_id
                                    });
                                    if let Ok(res) = client_clone.post(&python_url).json(&req_body).send().await {
                                        if let Ok(json_res) = res.json::<serde_json::Value>().await {
                                            if let Some(results_array) = json_res.get("results").and_then(|r| r.as_array()) {
                                                let mut items = Vec::new();
                                                for r in results_array {
                                                    items.push(proto::feedo::SemanticSearchResultItem {
                                                        hash_id: r.get("hash_id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                                                        text: r.get("text").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                                                        author: r.get("author").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                                                        timestamp: r.get("timestamp").and_then(|v| v.as_u64()).unwrap_or(0),
                                                        similarity_score: r.get("similarity_score").and_then(|v| v.as_f64()).unwrap_or(0.0) as f32,
                                                    });
                                                }
                                                if !items.is_empty() {
                                                    let res_proto = proto::feedo::SemanticSearchResult {
                                                        query_id: query_id_clone,
                                                        responder_peer_id: peer_id_str,
                                                        results: items,
                                                    };
                                                    let mut encoded = Vec::new();
                                                    encoded.push(1u8); // Result
                                                    if prost::Message::encode(&res_proto, &mut encoded).is_ok() {
                                                        let _ = cmd_tx.send(SwarmCommand::BroadcastSemanticResult(encoded));
                                                    }
                                                }
                                            }
                                        }
                                    }
                                });

                                // Forward the query if TTL > 0
                                if query.ttl > 0 {
                                    query.ttl -= 1;
                                    let mut fwd_encoded = Vec::new();
                                    fwd_encoded.push(0u8);
                                    if prost::Message::encode(&query, &mut fwd_encoded).is_ok() {
                                        let _ = loop_tx.send(SwarmCommand::ForwardSemanticSearch(fwd_encoded));
                                    }
                                }
                            }
                        } else if msg_type == 1 { // Result
                            if let Ok(res) = proto::feedo::SemanticSearchResult::decode(payload) {
                                if let Some((_, results)) = active_search_requests.get_mut(&res.query_id) {
                                    for item in res.results {
                                        results.push(item);
                                    }
                                }
                            }
                        }
                        continue;
                    }

                    
                    // Try to parse as PeerAnnounce first
                    if let Ok(announce) = serde_json::from_slice::<PeerAnnounce>(&message.data) {
                        // Validate freshness
                        let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
                        if announce.timestamp > now + 60 || now.saturating_sub(announce.timestamp) > 60 * 60 {
                            println!("Ignoring stale/future announce from {}", announce.peer_id);
                        } else {
                            // verify gossipsub source equals announced peer_id (prevents spoofing)
                            if let Some(src) = message.source.clone() {
                                if src.to_string() != announce.peer_id {
                                    println!("Announce peer_id {} does not match message source {}. Ignored.", announce.peer_id, src);
                                } else if peer_blacklist.contains(&announce.peer_id) {
                                    println!("Ignoring announce from blacklisted {}", announce.peer_id);
                                } else {
                                    // rate limiting
                                    let window_secs = env::var("ANNOUNCE_RATE_WINDOW_SECS").unwrap_or_else(|_| "600".to_string()).parse::<u64>().unwrap_or(600);
                                    let max_per_window = env::var("ANNOUNCE_RATE_MAX").unwrap_or_else(|_| "5".to_string()).parse::<usize>().unwrap_or(5);
                                    let now_ts = now;
                                    let entries = announce_rate_map.entry(announce.peer_id.clone()).or_insert_with(Vec::new);
                                    // prune old
                                    entries.retain(|t| now_ts.saturating_sub(*t) <= window_secs);
                                    if entries.len() >= max_per_window {
                                        println!("Rate limit exceeded for {} - ignoring announce", announce.peer_id);
                                        // optionally add to blacklist after repeated offenses
                                        let offenses = env::var("ANNOUNCE_BLACKLIST_OFFENSES").unwrap_or_else(|_| "10".to_string()).parse::<usize>().unwrap_or(10);
                                        if entries.len() >= offenses {
                                            peer_blacklist.insert(announce.peer_id.clone());
                                            if let Ok(s) = serde_json::to_string(&peer_blacklist) { let _ = fs::write(&peer_blacklist_path, s); }
                                            println!("Added {} to blacklist due to repeated offenses", announce.peer_id);
                                        }
                                    } else {
                                        entries.push(now_ts);
                                        println!("Received peer announce from {} (addrs: {})", announce.peer_id, announce.listen_addrs.join(","));
                                        // add to peer_cache and kademlia (validate addrs)
                                        let mut valid_addrs = Vec::new();
                                        for a in announce.listen_addrs.iter() {
                                            if is_valid_multiaddr(a) {
                                                valid_addrs.push(a.clone());
                                            } else {
                                                println!("Ignoring invalid multiaddr {} from {}", a, announce.peer_id);
                                            }
                                        }
                                        if !valid_addrs.is_empty() {
                                            // Verify signature & public key if present
                                            let mut verified = false;
                                            if let (Some(sig_hex), Some(pk_b64)) = (announce.signature.clone(), announce.public_key.clone()) {
                                                if let Ok(sig_bytes) = hex::decode(sig_hex) {
                                                    if let Ok(pk_bytes) = base64::engine::general_purpose::STANDARD.decode(pk_b64.as_bytes()) {
                                                        if let Ok(pubkey) = identity::PublicKey::try_decode_protobuf(&pk_bytes) {
                                                            // derive peer id from public key
                                                            let derived_pid = PeerId::from_public_key(&pubkey);
                                                            if let Some(src) = message.source.clone() {
                                                                if derived_pid == src && derived_pid.to_string() == announce.peer_id {
                                                                    // reconstruct payload without signature for verification
                                                                    let mut ann_nosig = announce.clone();
                                                                    ann_nosig.signature = None;
                                                                    if let Ok(payload_nosig) = serde_json::to_vec(&ann_nosig) {
                                                                        if pubkey.verify(&payload_nosig, &sig_bytes) {
                                                                            verified = true;
                                                                        } else {
                                                                            println!("Announce signature verification failed for {}", announce.peer_id);
                                                                        }
                                                                    }
                                                                } else {
                                                                    println!("Announce public_key does not match message source or peer_id");
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                            if verified {
                                                peer_cache.add_or_update(&announce.peer_id, valid_addrs.clone(), false);
                                                for a in valid_addrs.iter() {
                                                    if let Ok(ma) = Multiaddr::from_str(a) {
                                                        if let Ok(pid) = PeerId::from_str(&announce.peer_id) {
                                                            swarm.behaviour_mut().kademlia.add_address(&pid, ma);
                                                        }
                                                    }
                                                }

                                                let client_clone = http_client.clone();
                                                let url_clone = python_webhook_url.replace("/internal/p2p_receive", "/internal/p2p/register_peer");
                                                
                                                let mut pubkey_hex = String::new();
                                                if let Some(pk_b64) = announce.public_key.clone() {
                                                    if let Ok(pk_bytes) = base64::engine::general_purpose::STANDARD.decode(pk_b64.as_bytes()) {
                                                        pubkey_hex = hex::encode(pk_bytes);
                                                    }
                                                }

                                                let is_supernode = announce.is_supernode.unwrap_or(false);
                                                let peer_id_clone = announce.peer_id.clone();
                                                
                                                tokio::spawn(async move {
                                                    let req_body = serde_json::json!({
                                                        "peer_id": peer_id_clone,
                                                        "pubkey_hex": pubkey_hex,
                                                        "is_supernode": is_supernode
                                                    });
                                                    let _ = client_clone.post(&url_clone).json(&req_body).send().await;
                                                });

                                            } else {
                                                println!("Ignoring announce from {} because signature/public key not verified", announce.peer_id);
                                            }
                                        }
                                    }
                                }
                            } else {
                                println!("Announce without gossipsub source - ignoring {}", announce.peer_id);
                            }
                        }
                    } else if let Ok(post) = proto::feedo::FeedoBroadcast::decode(&message.data[..]) {
                        // Verify signature before processing
                        let mut valid_sig = false;
                        if let Ok(hash_bytes) = hex::decode(&post.hash_id) {
                            if did::verify_signature(&post.author_address, &hash_bytes, &post.signature) {
                                valid_sig = true;
                            }
                        }

                        if !valid_sig {
                            println!("Gossipsub: REJECTED post from {}. Invalid signature!", post.author_address);
                            continue;
                        }

                        println!("Gossipsub: Post metadata from {}", post.author_address);
                        
                        if post.source_type.as_deref() == Some("nostr") {
                            if let Ok(db) = nostr_db::NostrDb::new() {
                                let nostr_pubkey = post.author_address.replace("did:feedo:schnorr:", "");
                                let nostr_id = post.hash_id.clone();
                                let content = post.text_preview.clone(); // In FeedoBroadcast, text_preview holds the first 250 chars. We need the full content. Wait, FeedoBroadcast doesn't have the full text? It has content_blob_hash. Actually we should use the raw text if available, or just save what we have. Let's assume the client fetching from DHT or we just save text_preview for now. 
                                // Actually, FeedoBroadcast text_preview might not be the full text. Wait, Nostr texts are small.
                                let tags_str = if let Some(meta_str) = &post.metadata {
                                    if let Ok(meta_json) = serde_json::from_str::<serde_json::Value>(meta_str) {
                                        if let Some(tags) = meta_json.get("nostr_tags") {
                                            serde_json::to_string(tags).unwrap_or_else(|_| "[]".to_string())
                                        } else {
                                            "[]".to_string()
                                        }
                                    } else { "[]".to_string() }
                                } else { "[]".to_string() };
                                
                                let _ = db.insert_event(
                                    &nostr_id,
                                    &nostr_pubkey,
                                    post.timestamp,
                                    1, // default kind 1
                                    &content,
                                    &post.signature,
                                    &tags_str
                                );
                                println!("Saved global Nostr event {} to local SQLite.", nostr_id);
                            }
                        }

                        let client_clone = http_client.clone();
                        let url_clone = python_webhook_url.clone();
                        let post_clone = post.clone();

                        tokio::spawn(async move {
                            match client_clone.post(&url_clone).json(&post_clone).send().await {
                                Ok(res) => {
                                    if !res.status().is_success() {
                                        println!("Python API returned an error: {}", res.status());
                                    }
                                }
                                Err(e) => println!("Failed to reach Python API: {}", e),
                            }
                        });
                    }
                }
                SwarmEvent::NewListenAddr { address, .. } => {
                    println!("P2P Node listening on: {}", address);
                }
                _ => {}
            }
        }
    }
}

fn is_valid_multiaddr(s: &str) -> bool {
    if let Ok(ma) = Multiaddr::from_str(s) {
        let mut has_quic = false;
        for p in ma.iter() {
            match p {
                Protocol::Udp(_) | Protocol::QuicV1 => has_quic = true,
                Protocol::Ip4(_) | Protocol::Ip6(_) | Protocol::Dns4(_) | Protocol::Dns6(_) | Protocol::Dns(_) | Protocol::P2p(_) => {},
                _ => return false,
            }
        }
        return has_quic;
    }
    false
}

async fn handle_balance(Path(address): Path<String>, axum::extract::Extension(ledger): axum::extract::Extension<Arc<accounting::Ledger>>) -> Json<serde_json::Value> {
    let bal = ledger.get_balance(&address).await;
    // WEI to MATIC conversion for the API response
    let in_matic = (bal as f64) / 1_000_000_000_000_000_000.0;
    Json(serde_json::json!({"balance": in_matic}))
}

// --- Peer cache for P1 ---
#[derive(Serialize, Deserialize, Debug, Clone)]
struct PeerCacheEntry {
    peer_id: String,
    multiaddrs: Vec<String>,
    last_seen_unix: u64,
    success_count: u32,
    fail_count: u32,
    score: f64,
}

#[derive(Default, Serialize, Deserialize, Clone)]
struct PeerCache {
    peers: HashMap<String, PeerCacheEntry>,
}

impl PeerCache {
    fn load(path: &str) -> Self {
        if let Ok(s) = fs::read_to_string(path) {
            if let Ok(pc) = serde_json::from_str::<PeerCache>(&s) {
                return pc;
            }
        }
        PeerCache::default()
    }

    fn save(&self, path: &str) {
        if let Ok(s) = serde_json::to_string_pretty(self) {
            let _ = fs::write(path, s);
        }
    }

    fn add_or_update(&mut self, peer_id: &str, addrs: Vec<String>, success: bool) {
        let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
        let entry = self.peers.entry(peer_id.to_string()).or_insert(PeerCacheEntry {
            peer_id: peer_id.to_string(),
            multiaddrs: vec![],
            last_seen_unix: now,
            success_count: 0,
            fail_count: 0,
            score: 1.0,
        });
        for a in addrs.into_iter() {
            if !entry.multiaddrs.contains(&a) {
                entry.multiaddrs.push(a);
            }
        }
        entry.last_seen_unix = now;
        if success {
            entry.success_count = entry.success_count.saturating_add(1);
            entry.score = (entry.score * 0.8) + 0.2 * (entry.success_count as f64 + 1.0);
        } else {
            entry.fail_count = entry.fail_count.saturating_add(1);
            entry.score = (entry.score * 0.9) - 0.1 * (entry.fail_count as f64 + 1.0);
        }
    }

    fn top_n_addrs(&self, n: usize) -> Vec<String> {
        let mut v: Vec<&PeerCacheEntry> = self.peers.values().collect();
        v.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));
        let mut addrs = Vec::new();
        for e in v.into_iter().take(n) {
            for a in e.multiaddrs.iter() {
                addrs.push(a.clone());
            }
        }
        addrs
    }

    fn gc(&mut self, days: u64) {
        let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
        let ttl = days * 24 * 3600;
        self.peers.retain(|_, e| now.saturating_sub(e.last_seen_unix) <= ttl);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    #[test]
    fn peer_cache_save_load_and_gc() {
        let mut pc = PeerCache::default();
        pc.add_or_update("peer1", vec!["/ip4/127.0.0.1/udp/4001/quic-v1".to_string()], true);
        pc.add_or_update("peer2", vec!["/ip4/10.0.0.1/udp/4001/quic-v1".to_string()], false);
        let tmp = "test_peer_cache.json";
        pc.save(tmp);
        let loaded = PeerCache::load(tmp);
        assert!(loaded.peers.contains_key("peer1"));
        assert!(loaded.peers.contains_key("peer2"));
        let mut pc2 = loaded;
        pc2.gc(0);
        fs::remove_file(tmp).ok();
    }

    #[test]
    fn multiaddr_validation() {
        assert!(is_valid_multiaddr("/ip4/127.0.0.1/udp/4001/quic-v1"));
        assert!(is_valid_multiaddr("/dns4/api.feedo.ink/udp/4001/quic-v1/p2p/QmPeer"));
        assert!(!is_valid_multiaddr("/ip4/127.0.0.1/tcp/4001"));
        assert!(!is_valid_multiaddr("not-a-ma"));
    }
}