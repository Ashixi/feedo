use tonic::{transport::Server, Request, Response, Status};
use serde_json::json;
use std::time::{SystemTime, UNIX_EPOCH};

pub mod farcaster {
    tonic::include_proto!("farcaster");
}

use farcaster::hub_service_server::{HubService, HubServiceServer};
use farcaster::Message;

#[derive(Default)]
pub struct FeedoFarcasterHub {}

#[tonic::async_trait]
impl HubService for FeedoFarcasterHub {
    async fn submit_message(
        &self,
        request: Request<Message>,
    ) -> Result<Response<Message>, Status> {
        let msg = request.into_inner();
        
        println!("Received Farcaster Message.");
        
        if let Some(data) = &msg.data {
            println!("FID: {}, Type: {}", data.fid, data.r#type);
            
            // Type == 1 usually means CastAdd
            if let Some(farcaster::message_data::Body::CastAddBody(cast)) = &data.body {
                println!("New Cast Text: {}", cast.text);
                
                let author = format!("farcaster_fid_{}", data.fid);
                let timestamp = SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap()
                    .as_secs();

                // Build FeedoBroadcast JSON
                let feedo_broadcast = json!({
                    "text": cast.text,
                    "author": author,
                    "signature": hex::encode(&msg.signature),
                    "hash_id": hex::encode(&msg.hash),
                    "content_blob_hash": "",
                    "title": "",
                    "source_type": "farcaster",
                    "sequence_number": data.timestamp, // Using farcaster timestamp as seq
                    "timestamp": timestamp,
                    "metadata_": {}
                });

                // Post to Feedo API (FastAPI)
                let api_url = std::env::var("FEEDO_API_URL").unwrap_or_else(|_| "http://127.0.0.1:8041/local/publish".to_string());
                let client = reqwest::Client::new();
                let msg_hash_hex = hex::encode(&msg.hash);
                
                // Spawn the request in the background so we don't block the gRPC response
                tokio::spawn(async move {
                    match client.post(&api_url).json(&feedo_broadcast).send().await {
                        Ok(res) => {
                            if res.status().is_success() {
                                println!("Successfully bridged Farcaster Cast {} to Feedo DHT", msg_hash_hex);
                            } else {
                                eprintln!("Failed to bridge to Feedo API: HTTP {}", res.status());
                            }
                        }
                        Err(e) => eprintln!("Error calling Feedo API: {:?}", e),
                    }
                });
            }
        }

        // Return the unmodified message back to the client as Farcaster protocol requires
        Ok(Response::new(msg))
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let port = std::env::var("FARCASTER_PORT").unwrap_or_else(|_| "2283".to_string());
    let addr = format!("0.0.0.0:{}", port).parse()?;
    
    let hub = FeedoFarcasterHub::default();

    println!("🚀 Starting Hybrid Farcaster Ingress Node on {}", addr);
    println!("Waiting for Casts from Farcaster clients...");

    Server::builder()
        .add_service(HubServiceServer::new(hub))
        .serve(addr)
        .await?;

    Ok(())
}
