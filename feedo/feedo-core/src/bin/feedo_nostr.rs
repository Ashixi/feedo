use std::net::SocketAddr;
use tokio::net::{TcpListener, TcpStream};
use tokio_tungstenite::tungstenite::protocol::Message;
use tokio_tungstenite::accept_async;
use futures_util::{StreamExt, SinkExt};
use serde_json::Value;
use reqwest::Client;

const FEEDO_CORE_PUBLISH_URL: &str = "http://127.0.0.1:8041/local/publish";
const FEEDO_API_SEMANTIC_URL: &str = "http://127.0.0.1:8040/api/v1/semantic/query";

#[tokio::main]
async fn main() {
    println!("Starting Feedo-Nostr Hybrid Relay...");
    
    let addr = "0.0.0.0:8080".to_string();
    let listener = TcpListener::bind(&addr).await.expect("Failed to bind");
    println!("Nostr WebSocket Server listening on: {}", addr);

    let http_client = Client::new();

    while let Ok((stream, _)) = listener.accept().await {
        let peer = stream.peer_addr().expect("Connected streams should have a peer address");
        let client_clone = http_client.clone();
        tokio::spawn(accept_connection(peer, stream, client_clone));
    }
}

async fn accept_connection(peer: SocketAddr, stream: TcpStream, http_client: Client) {
    println!("New Nostr client connected: {}", peer);
    
    let ws_stream = match accept_async(stream).await {
        Ok(ws) => ws,
        Err(e) => {
            println!("Error during the websocket handshake: {}", e);
            return;
        }
    };
    
    let (mut write, mut read) = ws_stream.split();

    while let Some(msg_result) = read.next().await {
        match msg_result {
            Ok(msg) => {
                if msg.is_text() {
                    let text = msg.to_text().unwrap();
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
                                    
                                    if let Some(content) = event["content"].as_str() {
                                        let author_hex = event["pubkey"].as_str().unwrap_or("");
                                        // 1. Map Nostr Pubkey to Feedo DID
                                        let did = format!("did:feedo:schnorr:{}", author_hex);
                                        
                                        // 2. Prepare metadata
                                        let mut metadata = serde_json::Map::new();
                                        metadata.insert("nostr_id".to_string(), Value::String(event_id.to_string()));
                                        if let Some(tags) = event["tags"].as_array() {
                                            metadata.insert("nostr_tags".to_string(), Value::Array(tags.clone()));
                                        }
                                        
                                        // 3. Transform to Feedo PublishRequest format
                                        let payload = serde_json::json!({
                                            "text": content,
                                            "author": did,
                                            "signature": event["sig"].as_str().unwrap_or(""),
                                            "hash_id": event_id,
                                            "source_type": "nostr",
                                            "metadata": serde_json::to_string(&metadata).unwrap_or_default()
                                        });
                                        
                                        // 4. Send to Feedo Core IPC
                                        println!("Ingesting Nostr EVENT {} into Feedo...", event_id);
                                        let _ = http_client.post(FEEDO_CORE_PUBLISH_URL)
                                            .json(&payload)
                                            .send().await;
                                    }
                                    
                                    let response = format!("[\"OK\", \"{}\", true, \"\"]", event_id);
                                    let _ = write.send(Message::Text(response)).await;
                                }
                            },
                            "REQ" => {
                                if json_array.len() > 2 {
                                    let sub_id = json_array[1].as_str().unwrap_or("");
                                    println!("Received REQ: {}", sub_id);
                                    
                                    // Iterate through all filters in the REQ array
                                    for i in 2..json_array.len() {
                                        let filter = &json_array[i];
                                        
                                        // Check if this Nostr query is requesting a Semantic Search
                                        if let Some(search_query) = filter["search"].as_str() {
                                            println!("Triggering Semantic AI Search for: {}", search_query);
                                            
                                            let payload = serde_json::json!({
                                                "query": search_query,
                                                "limit": filter["limit"].as_u64().unwrap_or(20)
                                            });
                                            
                                            // 5. Query Feedo Python Vector API
                                            if let Ok(res) = http_client.post(FEEDO_API_SEMANTIC_URL)
                                                .json(&payload)
                                                .send().await 
                                            {
                                                if let Ok(results) = res.json::<Vec<Value>>().await {
                                                    // 6. Transform Semantic Results back to Nostr Events
                                                    for hit in results {
                                                        // Convert DID back to Nostr hex if possible
                                                        let raw_author = hit["author"].as_str().unwrap_or("");
                                                        let nostr_pubkey = raw_author.replace("did:feedo:schnorr:", "");
                                                        
                                                        let n_event = serde_json::json!([
                                                            "EVENT",
                                                            sub_id,
                                                            {
                                                                "id": hit["hash_id"].as_str().unwrap_or(""),
                                                                "pubkey": nostr_pubkey,
                                                                "created_at": hit["timestamp"].as_u64().unwrap_or(0),
                                                                "kind": 1,
                                                                "content": hit["text"].as_str().unwrap_or(""),
                                                                "tags": [],
                                                                "sig": "feedo_semantic_search_result"
                                                            }
                                                        ]);
                                                        let _ = write.send(Message::Text(n_event.to_string())).await;
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    
                                    let response = format!("[\"EOSE\", \"{}\"]", sub_id);
                                    let _ = write.send(Message::Text(response)).await;
                                }
                            },
                            "CLOSE" => {
                                if json_array.len() > 1 {
                                    let sub_id = json_array[1].as_str().unwrap_or("");
                                    println!("Received CLOSE for sub: {}", sub_id);
                                }
                            },
                            _ => {
                                println!("Unknown Nostr message type: {}", msg_type);
                            }
                        }
                    }
                }
            },
            Err(e) => {
                println!("Error processing message from {}: {}", peer, e);
                break;
            }
        }
    }
    
    println!("Nostr client disconnected: {}", peer);
}
