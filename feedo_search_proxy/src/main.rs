use futures_util::{SinkExt, StreamExt};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::env;
use tokio::net::{TcpListener, TcpStream};
use tokio_tungstenite::{
    accept_async, connect_async,
    tungstenite::protocol::Message,
};

#[derive(Serialize)]
struct SearchRequest {
    client_pubkey: String,
    relay_pubkey: String,
    query: String,
}

#[tokio::main]
async fn main() {
    let listen_addr = env::var("LISTEN_ADDR").unwrap_or_else(|_| "127.0.0.1:8080".to_string());
    let upstream_url = env::var("UPSTREAM_URL").unwrap_or_else(|_| "ws://127.0.0.1:8081".to_string());
    let feedo_api_url = env::var("FEEDO_API_URL").unwrap_or_else(|_| "http://127.0.0.1:8000/api/v1/relay_search".to_string());
    let relay_pubkey = env::var("RELAY_PUBKEY").unwrap_or_else(|_| "default_relay_pubkey".to_string());

    println!("Starting Feedo Search Proxy...");
    println!("Listening on: {}", listen_addr);
    println!("Upstream Relay: {}", upstream_url);
    println!("Feedo API: {}", feedo_api_url);

    let listener = TcpListener::bind(&listen_addr).await.expect("Failed to bind");

    while let Ok((stream, _)) = listener.accept().await {
        let upstream_url = upstream_url.clone();
        let feedo_api_url = feedo_api_url.clone();
        let relay_pubkey = relay_pubkey.clone();

        tokio::spawn(async move {
            if let Err(e) = handle_connection(stream, upstream_url, feedo_api_url, relay_pubkey).await {
                eprintln!("Error handling connection: {:?}", e);
            }
        });
    }
}

async fn handle_connection(
    client_stream: TcpStream,
    upstream_url: String,
    feedo_api_url: String,
    relay_pubkey: String,
) -> Result<(), Box<dyn std::error::Error>> {
    let client_ws = accept_async(client_stream).await?;
    let (mut client_tx, mut client_rx) = client_ws.split();

    let (upstream_ws, _) = connect_async(&upstream_url).await?;
    let (mut upstream_tx, mut upstream_rx) = upstream_ws.split();

    let http_client = Client::new();
    
    // In a real implementation, we would send ["AUTH", "challenge"] and wait for the client's pubkey.
    // For this MVP, we simulate a known client or anonymous.
    let mut client_pubkey = "anonymous_client".to_string();

    loop {
        tokio::select! {
            msg = client_rx.next() => {
                match msg {
                    Some(Ok(msg)) => {
                        if let Message::Text(text) = &msg {
                            if let Ok(json) = serde_json::from_str::<Value>(text) {
                                if let Some(arr) = json.as_array() {
                                    // Handle AUTH
                                    if arr.len() >= 2 && arr[0] == "AUTH" {
                                        if let Some(event) = arr[1].as_object() {
                                            if let Some(pubkey) = event.get("pubkey").and_then(|v| v.as_str()) {
                                                client_pubkey = pubkey.to_string();
                                                println!("Authenticated client: {}", client_pubkey);
                                            }
                                        }
                                    }

                                    // Handle REQ with search
                                    if arr.len() >= 3 && arr[0] == "REQ" {
                                        if let Some(sub_id) = arr[1].as_str() {
                                            let mut is_search = false;
                                            let mut search_query = String::new();

                                            for filter in arr.iter().skip(2) {
                                                if let Some(f_obj) = filter.as_object() {
                                                    if let Some(search_val) = f_obj.get("search").and_then(|v| v.as_str()) {
                                                        is_search = true;
                                                        search_query = search_val.to_string();
                                                        break;
                                                    }
                                                }
                                            }

                                            if is_search {
                                                println!("Intercepted NIP-50 search for '{}' from {}", search_query, client_pubkey);
                                                
                                                // Send to Feedo API
                                                let req = SearchRequest {
                                                    client_pubkey: client_pubkey.clone(),
                                                    relay_pubkey: relay_pubkey.clone(),
                                                    query: search_query,
                                                };

                                                match http_client.post(&feedo_api_url).json(&req).send().await {
                                                    Ok(res) => {
                                                        if res.status().is_success() {
                                                            if let Ok(events) = res.json::<Vec<Value>>().await {
                                                                for event in events {
                                                                    let out_msg = serde_json::json!(["EVENT", sub_id, event]);
                                                                    client_tx.send(Message::Text(out_msg.to_string().into())).await?;
                                                                }
                                                            }
                                                            let eose = serde_json::json!(["EOSE", sub_id]);
                                                            client_tx.send(Message::Text(eose.to_string().into())).await?;
                                                        } else if res.status().as_u16() == 402 {
                                                            let notice = serde_json::json!(["NOTICE", "Payment Required: Please top up your Feedo balance to use search. You have exhausted your free quota."]);
                                                            client_tx.send(Message::Text(notice.to_string().into())).await?;
                                                            let eose = serde_json::json!(["EOSE", sub_id]);
                                                            client_tx.send(Message::Text(eose.to_string().into())).await?;
                                                        } else {
                                                            let notice = serde_json::json!(["NOTICE", "Feedo Search Error"]);
                                                            client_tx.send(Message::Text(notice.to_string().into())).await?;
                                                        }
                                                    }
                                                    Err(e) => {
                                                        eprintln!("Feedo API error: {}", e);
                                                        let notice = serde_json::json!(["NOTICE", "Search API unavailable"]);
                                                        client_tx.send(Message::Text(notice.to_string().into())).await?;
                                                    }
                                                }
                                                continue; // Skip sending to upstream
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        
                        // Pass through to upstream
                        upstream_tx.send(msg).await?;
                    }
                    Some(Err(e)) => {
                        eprintln!("Client error: {}", e);
                        break;
                    }
                    None => break,
                }
            }
            msg = upstream_rx.next() => {
                match msg {
                    Some(Ok(msg)) => {
                        client_tx.send(msg).await?;
                    }
                    Some(Err(e)) => {
                        eprintln!("Upstream error: {}", e);
                        break;
                    }
                    None => break,
                }
            }
        }
    }

    Ok(())
}
