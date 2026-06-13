use tonic::{transport::Server, Request, Response, Status};

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
            
            if let Some(farcaster::message_data::Body::CastAddBody(cast)) = &data.body {
                println!("New Cast Text: {}", cast.text);
                
                // TODO: Map to FeedoBroadcast and store in Feedo DB
                // This bridges the Farcaster network into the Feedo Semantic Layer
            }
        }

        Ok(Response::new(msg))
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let addr = "0.0.0.0:2283".parse()?; // Standard Farcaster Hub RPC Port
    let hub = FeedoFarcasterHub::default();

    println!("Starting Farcaster gRPC Hub on {}", addr);

    Server::builder()
        .add_service(HubServiceServer::new(hub))
        .serve(addr)
        .await?;

    Ok(())
}
