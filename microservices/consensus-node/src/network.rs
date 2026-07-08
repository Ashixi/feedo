use libp2p::{gossipsub, identify, kad, mdns, request_response, swarm::NetworkBehaviour};
use serde::{Deserialize, Serialize};
use std::io;

/// Protocol name for transaction relay to validators.
pub const TX_PROTOCOL: &str = "/feedo-tx/1.0.0";

use libp2p::request_response::Codec as RrCodec;
use futures::AsyncReadExt;
use futures::AsyncWriteExt;

/// Custom JSON-based codec for request-response.
#[derive(Clone, Debug, Default)]
pub struct TxCodec;

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct TxRequest {
    pub tx_type: String,
    pub tx_data_json: String,
    pub from_node: String,
    pub signature: String,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct TxResponse {
    pub accepted: bool,
    pub reason: String,
}

#[async_trait::async_trait]
impl RrCodec for TxCodec {
    type Protocol = String;
    type Request = TxRequest;
    type Response = TxResponse;

    async fn read_request<T>(
        &mut self,
        _protocol: &Self::Protocol,
        io: &mut T,
    ) -> io::Result<Self::Request>
    where
        T: futures::AsyncRead + Send + Unpin,
    {
        let mut buf = Vec::new();
        io.read_to_end(&mut buf).await?;
        serde_json::from_slice(&buf).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))
    }

    async fn read_response<T>(
        &mut self,
        _protocol: &Self::Protocol,
        io: &mut T,
    ) -> io::Result<Self::Response>
    where
        T: futures::AsyncRead + Send + Unpin,
    {
        let mut buf = Vec::new();
        io.read_to_end(&mut buf).await?;
        serde_json::from_slice(&buf).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))
    }

    async fn write_request<T>(
        &mut self,
        _protocol: &Self::Protocol,
        io: &mut T,
        data: Self::Request,
    ) -> io::Result<()>
    where
        T: futures::AsyncWrite + Send + Unpin,
    {
        let json = serde_json::to_vec(&data).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
        io.write_all(&json).await
    }

    async fn write_response<T>(
        &mut self,
        _protocol: &Self::Protocol,
        io: &mut T,
        data: Self::Response,
    ) -> io::Result<()>
    where
        T: futures::AsyncWrite + Send + Unpin,
    {
        let json = serde_json::to_vec(&data).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
        io.write_all(&json).await
    }
}

#[derive(NetworkBehaviour)]
pub struct ConsensusBehaviour {
    pub gossipsub: gossipsub::Behaviour,
    pub kademlia: kad::Behaviour<kad::store::MemoryStore>,
    pub identify: identify::Behaviour,
    pub mdns: mdns::tokio::Behaviour,
    pub request_response: request_response::Behaviour<TxCodec>,
}