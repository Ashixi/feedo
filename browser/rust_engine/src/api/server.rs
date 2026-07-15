use axum::{
    extract::Host,
    http::{header, StatusCode, Uri},
    response::{IntoResponse, Response},
    Router,
};
use std::collections::HashMap;
use std::sync::{Mutex, OnceLock, RwLock};
use std::net::SocketAddr;
use std::io::{Read, Cursor};
use zip::ZipArchive;

type CacheMap = HashMap<String, HashMap<String, Vec<u8>>>;
static ARCHIVE_CACHE: OnceLock<Mutex<CacheMap>> = OnceLock::new();
static GATEWAYS: OnceLock<RwLock<Vec<String>>> = OnceLock::new();
static SWARM_TX: OnceLock<tokio::sync::mpsc::UnboundedSender<crate::api::swarm_loop::SwarmCommand>> = OnceLock::new();

fn get_cache() -> &'static Mutex<CacheMap> {
    ARCHIVE_CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

fn get_gateways() -> &'static RwLock<Vec<String>> {
    GATEWAYS.get_or_init(|| RwLock::new(vec![
        "https://api.feedo.ink".to_string(),
        "https://api2.feedo.ink".to_string()
    ]))
}

pub fn set_gateways(gateways: Vec<String>) -> anyhow::Result<()> {
    let mut current = get_gateways().write().unwrap();
    *current = gateways;
    Ok(())
}

pub fn start_local_server() -> anyhow::Result<()> {
    // We spawn the server in a new thread so we don't block Flutter
    std::thread::spawn(|| {
        let rt = tokio::runtime::Runtime::new().unwrap();
        rt.block_on(async {
            // Setup Light Node Swarm
            let local_key = libp2p::identity::Keypair::generate_ed25519();
            let local_peer_id = libp2p::PeerId::from(local_key.public());
            
            let mut swarm = libp2p::SwarmBuilder::with_existing_identity(local_key.clone())
                .with_tokio()
                .with_tcp(
                    libp2p::tcp::Config::default(),
                    libp2p::noise::Config::new,
                    libp2p::yamux::Config::default,
                ).unwrap()
                .with_quic()
                .with_dns().unwrap()
                .with_behaviour(|key| {
                    let mut kad_config = libp2p::kad::Config::default();
                    kad_config.set_query_timeout(std::time::Duration::from_secs(10));
                    let mut kademlia = libp2p::kad::Behaviour::with_config(
                        local_peer_id, 
                        libp2p::kad::store::MemoryStore::new(local_peer_id), 
                        kad_config
                    );
                    kademlia.set_mode(Some(libp2p::kad::Mode::Client));
                    
                    crate::api::network::StorageBehaviour {
                        kademlia,
                        gossipsub: libp2p::gossipsub::Behaviour::new(
                            libp2p::gossipsub::MessageAuthenticity::Signed(key.clone()),
                            libp2p::gossipsub::ConfigBuilder::default().build().unwrap(),
                        ).unwrap(),
                        identify: libp2p::identify::Behaviour::new(libp2p::identify::Config::new("/feedo/1.0.0".to_string(), key.public())),
                        mdns: libp2p::mdns::tokio::Behaviour::new(libp2p::mdns::Config::default(), local_peer_id).unwrap(),
                        req_resp: libp2p::request_response::cbor::Behaviour::new(
                            [(libp2p::StreamProtocol::new("/feedo/chunks/1.0.0"), libp2p::request_response::ProtocolSupport::Full)],
                            libp2p::request_response::Config::default(),
                        ),
                    }
                }).unwrap()
                .with_swarm_config(|c| c.with_idle_connection_timeout(std::time::Duration::from_secs(60)))
                .build();
            
    let bootstrap_nodes = vec![
        // api.feedo.ink (95.111.245.68)
        "/dns4/api.feedo.ink/udp/8040/quic-v1/p2p/12D3KooWD1ErUyHizJHEP2KzSfGxbLS9wN88vVUpM7FeyLPbrp39",
        "/dns4/api.feedo.ink/udp/8041/quic-v1/p2p/12D3KooWHKWyZDgVpw65ruHBFvHwXSJ5LHGKTHn7DYbtrwo7gFtg",
        // api2.feedo.ink (178.18.253.94)
        "/dns4/api2.feedo.ink/udp/8040/quic-v1/p2p/12D3KooWHgoEKnniktRFUuYXw6zZFJhKEvgK7ajJXYZpGYRVJwBj",
        "/dns4/api2.feedo.ink/udp/8041/quic-v1/p2p/12D3KooWMJfThcTD3GiKMz4ihKkZHG3iYZKoaNTxFdTJV49kvmMh"
    ];
            for node in bootstrap_nodes {
                if let Ok(addr) = node.parse::<libp2p::Multiaddr>() {
                    match swarm.dial(addr.clone()) {
                        Ok(_) => println!("Dialing {}...", addr),
                        Err(e) => println!("Error dialing {}: {:?}", addr, e),
                    }
                }
            }

            let (tx, rx) = tokio::sync::mpsc::unbounded_channel();
            let _ = SWARM_TX.set(tx); // ignore error on hot-restart

            tokio::spawn(crate::api::swarm_loop::run_swarm(swarm, rx));

            let app = Router::new().fallback(handle_request);
            
            let addr = SocketAddr::from(([127, 0, 0, 1], 8081));
            let listener_res = tokio::net::TcpListener::bind(addr).await;
            let listener = match listener_res {
                Ok(l) => l,
                Err(e) if e.kind() == std::io::ErrorKind::AddrInUse => {
                    println!("Port 8081 is already in use, assuming LocalFeedoServer is already running from previous run.");
                    return;
                }
                Err(e) => panic!("Failed to bind to {}: {}", addr, e),
            };
            
            println!("Local server listening on {}", addr);
            axum::serve(listener, app).await.unwrap();
        });
    });
    
    Ok(())
}

async fn handle_request(Host(host): Host, uri: Uri) -> impl IntoResponse {
    let host_parts: Vec<&str> = host.split('.').collect();
    if host_parts.len() < 2 {
        return (StatusCode::BAD_REQUEST, "Invalid host").into_response();
    }
    
    let mut cid = host_parts[0].to_string();
    if host_parts.len() >= 2 && host_parts[0].len() == 32 && host_parts[1].len() == 32 {
        cid.push_str(host_parts[1]);
    }
    let mut path = uri.path().to_string();
    if path == "/" || path.is_empty() {
        path = "/index.html".to_string();
    }
    
    // Remove leading slash
    let path = path.trim_start_matches('/').to_string();
    
    // Check if we have the file in cache
    let cached = {
        let cache = get_cache().lock().unwrap();
        if let Some(archive) = cache.get(&cid) {
            archive.get(&path).cloned()
        } else {
            None
        }
    };
    
    if let Some(data) = cached {
        return create_response(&path, data);
    }
    
    // If not in cache, fetch the ZIP
    match fetch_and_cache_zip(&cid).await {
        Ok(_) => {
            let cache = get_cache().lock().unwrap();
            if let Some(archive) = cache.get(&cid) {
                if let Some(data) = archive.get(&path) {
                    return create_response(&path, data.clone());
                }
            }
            (StatusCode::NOT_FOUND, "File not found in archive").into_response()
        },
        Err(e) => {
            (StatusCode::INTERNAL_SERVER_ERROR, format!("Failed to fetch archive: {}", e)).into_response()
        }
    }
}

fn extract_zip_to_cache(cid: &str, bytes: Vec<u8>) -> anyhow::Result<()> {
    let reader = Cursor::new(bytes);
    let mut zip = ZipArchive::new(reader).map_err(|_| anyhow::anyhow!("Invalid ZIP archive"))?;
    let mut raw_files = Vec::new();
    
    for i in 0..zip.len() {
        if let Ok(mut file) = zip.by_index(i) {
            if !file.is_dir() {
                let name = file.name().to_string();
                let mut buf = Vec::new();
                if file.read_to_end(&mut buf).is_ok() {
                    raw_files.push((name, buf));
                }
            }
        }
    }
    
    // Визначаємо спільну кореневу папку (напр. "dist/")
    let mut common_prefix = None;
    for (name, _) in &raw_files {
        let parts: Vec<&str> = name.split('/').collect();
        if parts.len() > 1 {
            let root_dir = format!("{}/", parts[0]);
            if let Some(ref current_prefix) = common_prefix {
                if current_prefix != &root_dir {
                    common_prefix = Some(String::new());
                    break;
                }
            } else {
                common_prefix = Some(root_dir);
            }
        } else {
            common_prefix = Some(String::new());
            break;
        }
    }
    
    let prefix_to_strip = common_prefix.unwrap_or_default();
    
    let mut files = HashMap::new();
    for (name, buf) in raw_files {
        let clean_name = if !prefix_to_strip.is_empty() && name.starts_with(&prefix_to_strip) {
            name.strip_prefix(&prefix_to_strip).unwrap_or(&name).to_string()
        } else {
            name
        };
        files.insert(clean_name, buf);
    }
    
    let mut cache = get_cache().lock().unwrap();
    cache.insert(cid.to_string(), files);
    Ok(())
}

/// Try to download a ZIP from storage-node via HTTP gateways.
async fn fetch_via_http(cid: &str) -> Option<Vec<u8>> {
    let gateways = get_gateways().read().unwrap().clone();
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .ok()?;

    for gateway in &gateways {
        let url = format!("{}/download/{}", gateway.trim_end_matches('/'), cid);
        println!("[LOCAL_SERVER] Trying HTTP fetch: {}", url);
        match client.get(&url).send().await {
            Ok(resp) if resp.status().is_success() => {
                match resp.bytes().await {
                    Ok(b) => {
                        println!("[LOCAL_SERVER] HTTP fetch SUCCESS from {} ({} bytes)", gateway, b.len());
                        return Some(b.to_vec());
                    }
                    Err(e) => println!("[LOCAL_SERVER] HTTP read error from {}: {}", gateway, e),
                }
            }
            Ok(resp) => println!("[LOCAL_SERVER] HTTP {} from {}", resp.status(), gateway),
            Err(e) => println!("[LOCAL_SERVER] HTTP fetch error from {}: {}", gateway, e),
        }
    }
    None
}

async fn fetch_and_cache_zip(cid: &str) -> anyhow::Result<()> {
    // 1. Try DHT first
    if let Some(tx) = SWARM_TX.get() {
        for retry in 0..3 {
            let (reply_tx, reply_rx) = tokio::sync::oneshot::channel();
            let _ = tx.send(crate::api::swarm_loop::SwarmCommand::DhtFetchFile(cid.to_string(), reply_tx));
            match reply_rx.await {
                Ok(Some(b)) => return extract_zip_to_cache(cid, b),
                Ok(None) => println!("[LOCAL_SERVER] DHT returned None for {} (retry {})", cid, retry),
                Err(e) => println!("[LOCAL_SERVER] DHT error for {}: {}", cid, e),
            }
            tokio::time::sleep(std::time::Duration::from_secs(2)).await;
        }
    }
    
    // 2. HTTP fallback — fetch from storage-node gateways
    println!("[LOCAL_SERVER] DHT failed for {}, trying HTTP gateways...", cid);
    if let Some(bytes) = fetch_via_http(cid).await {
        return extract_zip_to_cache(cid, bytes);
    }
    
    Err(anyhow::anyhow!("File not found in DHT or HTTP gateways for CID: {}", cid))
}


fn create_response(path: &str, data: Vec<u8>) -> Response {
    let mime_type = mime_guess::from_path(path).first_or_octet_stream();
    Response::builder()
        .header(header::CONTENT_TYPE, mime_type.as_ref())
        .body(axum::body::Body::from(data))
        .unwrap()
}
