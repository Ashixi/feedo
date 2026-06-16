use axum::{
    extract::ws::{Message as AxumMessage, WebSocket, WebSocketUpgrade},
    extract::State,
    http::header::{HeaderMap, ACCEPT},
    response::{IntoResponse, Response},
    routing::get,
    Router, Json,
};
use futures::{StreamExt, SinkExt};
use reqwest::Client;
use serde_json::Value;
use std::sync::Arc;
use tokio::sync::broadcast;

// Stateless Smart Proxy (No local DB)

const FEEDO_CORE_PUBLISH_URL: &str = "http://127.0.0.1:8041/local/publish";
const FEEDO_CORE_SEMANTIC_URL: &str = "http://127.0.0.1:8041/local/semantic_search";

fn verify_nostr_event(event: &Value) -> bool {
    use secp256k1::{Secp256k1, Message as SecpMessage, schnorr::Signature, XOnlyPublicKey};
    use sha2::{Sha256, Digest};
    use std::str::FromStr;

    let pubkey_str = event["pubkey"].as_str().unwrap_or("");
    let sig_str = event["sig"].as_str().unwrap_or("");
    let id_str = event["id"].as_str().unwrap_or("");
    
    let created_at = event["created_at"].as_u64().unwrap_or(0);
    let kind = event["kind"].as_u64().unwrap_or(0);
    let tags = event["tags"].as_array().unwrap_or(&vec![]).clone();
    let content = event["content"].as_str().unwrap_or("");

    let serialized = serde_json::json!([
        0,
        pubkey_str,
        created_at,
        kind,
        tags,
        content
    ]).to_string();

    let mut hasher = Sha256::new();
    hasher.update(serialized.as_bytes());
    let hash_result = hasher.finalize();
    let calculated_id = hex::encode(hash_result);

    if calculated_id != id_str {
        return false;
    }

    let secp = Secp256k1::new();
    if let Ok(pubkey) = XOnlyPublicKey::from_str(pubkey_str) {
        if let Ok(sig) = Signature::from_str(sig_str) {
            if let Ok(msg) = SecpMessage::from_digest_slice(&hash_result) {
                return secp.verify_schnorr(&sig, &msg, &pubkey).is_ok();
            }
        }
    }
    false
}

#[derive(Clone)]
struct AppState {
    http_client: Client,
    broadcast_tx: broadcast::Sender<Value>,
}

#[tokio::main]
async fn main() {
    println!("Starting Feedo-Nostr Hybrid Relay...");
    
    let http_client = Client::new();
    let (broadcast_tx, _) = broadcast::channel(1024);

    let state = AppState {
        http_client,
        broadcast_tx,
    };

    let app = Router::new()
        .route("/", get(ws_or_nip11_handler))
        .with_state(state);

    let listener = tokio::net::TcpListener::bind("0.0.0.0:8080").await.unwrap();
    println!("Nostr WebSocket Server listening on: 0.0.0.0:8080");
    axum::serve(listener, app).await.unwrap();
}

async fn ws_or_nip11_handler(
    headers: HeaderMap,
    ws: Option<WebSocketUpgrade>,
    State(state): State<AppState>,
) -> Response {
    if let Some(accept) = headers.get(ACCEPT) {
        if let Ok(accept_str) = accept.to_str() {
            if accept_str.contains("application/nostr+json") {
                let nip11 = serde_json::json!({
                    "name": "Feedo Hybrid Nostr Node",
                    "description": "Federated P2P Nostr Relay powered by Feedo AI",
                    "pubkey": "",
                    "contact": "",
                    "supported_nips": [11, 50],
                    "software": "git+https://github.com/feedo/feedo.git",
                    "version": "1.0.0"
                });
                return Json(nip11).into_response();
            }
        }
    }

    if let Some(ws) = ws {
        ws.on_upgrade(move |socket| handle_socket(socket, state))
    } else {
        "Please connect via Nostr WebSocket protocol or use Accept: application/nostr+json for NIP-11".into_response()
    }
}

async fn handle_socket(mut socket: WebSocket, state: AppState) {
    println!("New Nostr client connected");
    
    let mut rx = state.broadcast_tx.subscribe();
    
    // Create a local channel to merge messages sent to the client
    let (local_tx, mut local_rx) = tokio::sync::mpsc::channel::<AxumMessage>(100);
    
    // We need to handle both incoming websocket messages and incoming broadcast messages
    let subscriptions = Arc::new(std::sync::Mutex::new(std::collections::HashMap::<String, Vec<Value>>::new()));
    let subs_for_broadcast = subscriptions.clone();
    let local_tx_for_broadcast = local_tx.clone();
    
    // Task to listen to broadcasted live events
    tokio::spawn(async move {
        while let Ok(event) = rx.recv().await {
            let mut matched_subs = Vec::new();
            {
                let subs = subs_for_broadcast.lock().unwrap();
                for (sub_id, filters) in subs.iter() {
                    let kind = event["kind"].as_u64().unwrap_or(0);
                    let pubkey = event["pubkey"].as_str().unwrap_or("");
                    
                    let mut matches = false;
                    for filter in filters {
                        let mut filter_match = true;
                        if let Some(kinds) = filter["kinds"].as_array() {
                            if !kinds.iter().any(|k| k.as_u64() == Some(kind)) {
                                filter_match = false;
                            }
                        }
                        if let Some(authors) = filter["authors"].as_array() {
                            if !authors.iter().any(|a| a.as_str() == Some(pubkey)) {
                                filter_match = false;
                            }
                        }
                        if filter["search"].is_string() {
                            filter_match = false; // Simplified: live search generally disabled
                        }
                        
                        if filter_match {
                            matches = true;
                            break;
                        }
                    }
                    if matches {
                        matched_subs.push(sub_id.clone());
                    }
                }
            }
            
            for sub_id in matched_subs {
                let n_event = serde_json::json!(["EVENT", sub_id, event.clone()]);
                let _ = local_tx_for_broadcast.send(AxumMessage::Text(n_event.to_string())).await;
            }
        }
    });

    loop {
        tokio::select! {
            Some(msg) = local_rx.recv() => {
                if socket.send(msg).await.is_err() {
                    break;
                }
            }
            msg_result = socket.recv() => {
                match msg_result {
                    Some(Ok(msg)) => {
                        if let Ok(text) = msg.to_text() {
                            if let Ok(json_array) = serde_json::from_str::<Vec<Value>>(text) {
                                if json_array.is_empty() {
                                    continue;
                                }
                                
                                let msg_type = json_array[0].as_str().unwrap_or("");
                                match msg_type {
                                    "EVENT" => {
                                        if json_array.len() > 1 {
                                            let event = &json_array[1];
                                            let event_id = event["id"].as_str().unwrap_or("");
                                            
                                            if !verify_nostr_event(event) {
                                                let response = format!("[\"OK\", \"{}\", false, \"invalid: signature verification failed\"]", event_id);
                                                let _ = local_tx.send(AxumMessage::Text(response)).await;
                                                continue;
                                            }

                                            let pubkey_str = event["pubkey"].as_str().unwrap_or("");
                                            let sig_str = event["sig"].as_str().unwrap_or("");
                                            let created_at = event["created_at"].as_u64().unwrap_or(0);
                                            let kind = event["kind"].as_u64().unwrap_or(0);
                                            let tags_str = serde_json::to_string(&event["tags"]).unwrap_or_else(|_| "[]".to_string());
                                            
                                            let is_ephemeral = 20000 <= kind && kind < 30000;
                                            
                                            if let Some(content) = event["content"].as_str() {
                                                if !is_ephemeral {
                                                    // Send to Feedo Core IPC for Vectorization (No local text storage)
                                                    let author_hex = pubkey_str;
                                                    let did = format!("did:feedo:schnorr:{}", author_hex);
                                                    let mut metadata = serde_json::Map::new();
                                                    metadata.insert("nostr_id".to_string(), Value::String(event_id.to_string()));
                                                    if let Some(tags) = event["tags"].as_array() {
                                                        metadata.insert("nostr_tags".to_string(), Value::Array(tags.clone()));
                                                    }
                                                    let payload = serde_json::json!({
                                                        "text": content,
                                                        "author": did,
                                                        "signature": sig_str,
                                                        "hash_id": event_id,
                                                        "source_type": "nostr",
                                                        "metadata": serde_json::to_string(&metadata).unwrap_or_default()
                                                    });
                                                    let http_client_clone = state.http_client.clone();
                                                    tokio::spawn(async move {
                                                        let _ = http_client_clone.post(FEEDO_CORE_PUBLISH_URL).json(&payload).send().await;
                                                    });
                                                }
                                                
                                                // Broadcast to connected clients
                                                let _ = state.broadcast_tx.send(event.clone());
                                            }
                                            
                                            let response = format!("[\"OK\", \"{}\", true, \"\"]", event_id);
                                            let _ = local_tx.send(AxumMessage::Text(response)).await;
                                        }
                                    },
                                    "REQ" => {
                                        if json_array.len() > 2 {
                                            let sub_id = json_array[1].as_str().unwrap_or("");
                                            println!("Received REQ: {}", sub_id);
                                            
                                            let mut filters = Vec::new();
                                            
                                            for i in 2..json_array.len() {
                                                let filter = &json_array[i];
                                                filters.push(filter.clone());
                                                
                                                // Check if this Nostr query is requesting a Semantic Search
                                                if let Some(search_query) = filter["search"].as_str() {
                                                    println!("Triggering Semantic AI Search for: {}", search_query);
                                                    
                                                    let mut item_type = "post";
                                                    if let Some(kinds) = filter["kinds"].as_array() {
                                                        if kinds.iter().any(|k| k.as_u64() == Some(0)) {
                                                            item_type = "profile";
                                                        }
                                                    }
                                                    
                                                    let payload = serde_json::json!({
                                                        "text_query": search_query,
                                                        "limit": filter["limit"].as_u64().unwrap_or(20) as u32,
                                                        "source_types": ["nostr"], // Enforce searching only Nostr content
                                                        "item_type": item_type
                                                    });
                                                    let http_client_clone = state.http_client.clone();
                                                    let sub_id_clone = sub_id.to_string();
                                                    let local_tx_clone = local_tx.clone();
                                                    
                                                    tokio::spawn(async move {
                                                        if let Ok(res) = http_client_clone.post(FEEDO_CORE_SEMANTIC_URL).json(&payload).send().await {
                                                            if let Ok(res_json) = res.json::<serde_json::Value>().await {
                                                                if let Some(results) = res_json.get("results").and_then(|r| r.as_array()) {
                                                                    for hit in results {
                                                                        let hash_id = hit["hash_id"].as_str().unwrap_or("").to_string();
                                                                        
                                                                        let relay_urls: Vec<String> = if let Some(urls) = hit["relay_urls"].as_array() {
                                                                            urls.iter().filter_map(|v| v.as_str().map(String::from)).collect()
                                                                        } else if let Some(url) = hit["relay_url"].as_str() {
                                                                            vec![url.to_string()]
                                                                        } else {
                                                                            vec![]
                                                                        };
                                                                        
                                                                        if !relay_urls.is_empty() && !hash_id.is_empty() {
                                                                            let sub_id_inner = sub_id_clone.clone();
                                                                            let tx_inner = local_tx_clone.clone();
                                                                            
                                                                            tokio::spawn(async move {
                                                                                let mut event_found = false;
                                                                                for relay_url in relay_urls {
                                                                                    if event_found { break; }
                                                                                    
                                                                                    if let Ok(Ok((mut ws_stream, _))) = tokio::time::timeout(std::time::Duration::from_secs(5), tokio_tungstenite::connect_async(&relay_url)).await {
                                                                                        let req_id = format!("fetch_{}", hash_id);
                                                                                        let req = serde_json::json!(["REQ", req_id.clone(), { "ids": [hash_id] }]);
                                                                                        let _ = futures::SinkExt::send(&mut ws_stream, tokio_tungstenite::tungstenite::Message::Text(req.to_string())).await;
                                                                                        
                                                                                        while let Ok(Some(Ok(msg))) = tokio::time::timeout(std::time::Duration::from_secs(3), futures::StreamExt::next(&mut ws_stream)).await {
                                                                                            if let Ok(text) = msg.to_text() {
                                                                                                if let Ok(arr) = serde_json::from_str::<Vec<Value>>(text) {
                                                                                                    if arr.len() >= 3 && arr[0] == "EVENT" && arr[1] == req_id {
                                                                                                        let event = arr[2].clone();
                                                                                                        let n_event = serde_json::json!(["EVENT", sub_id_inner.clone(), event]);
                                                                                                        let _ = tx_inner.send(AxumMessage::Text(n_event.to_string())).await;
                                                                                                        event_found = true;
                                                                                                        break;
                                                                                                    } else if arr.len() >= 2 && arr[0] == "EOSE" && arr[1] == req_id {
                                                                                                        break;
                                                                                                    }
                                                                                                }
                                                                                            }
                                                                                        }
                                                                                    }
                                                                                }
                                                                            });
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                        }
                                                        let response = format!("[\"EOSE\", \"{}\"]", sub_id_clone);
                                                        let _ = local_tx_clone.send(AxumMessage::Text(response)).await;
                                                    });
                                                    continue;
                                                } else {
                                                    // As a Stateless Indexer, we don't serve regular queries, only searches.
                                                    // Just return EOSE immediately.
                                                }
                                            }
                                            
                                            // Save subscription for live events
                                            {
                                                let mut subs = subscriptions.lock().unwrap();
                                                subs.insert(sub_id.to_string(), filters);
                                            }
                                            
                                            let response = format!("[\"EOSE\", \"{}\"]", sub_id);
                                            let _ = local_tx.send(AxumMessage::Text(response)).await;
                                        }
                                    },
                                    "CLOSE" => {
                                        if json_array.len() > 1 {
                                            let sub_id = json_array[1].as_str().unwrap_or("");
                                            println!("Received CLOSE for sub: {}", sub_id);
                                            {
                                                let mut subs = subscriptions.lock().unwrap();
                                                subs.remove(sub_id);
                                            }
                                        }
                                    },
                                    _ => {
                                        println!("Unknown Nostr message type: {}", msg_type);
                                    }
                                }
                            }
                        }
                    }
                    Some(Err(e)) => {
                        println!("Error processing message: {}", e);
                        break;
                    }
                    None => break,
                }
            }
        }
    }
    
    println!("Nostr client disconnected");
}
