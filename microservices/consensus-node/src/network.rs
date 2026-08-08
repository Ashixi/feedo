use libp2p::{gossipsub, identify, kad, mdns, request_response, swarm::NetworkBehaviour};
use serde::{Deserialize, Serialize};
use std::io;

/// Protocol name for consensus messages (transaction relay + PBFT votes).
pub const CONSENSUS_PROTOCOL: &str = "/feedo-consensus/1.0.0";

/// Deprecated — kept for backward compatibility references.
pub const TX_PROTOCOL: &str = CONSENSUS_PROTOCOL;

use libp2p::request_response::Codec as RrCodec;
use futures::AsyncReadExt;
use futures::AsyncWriteExt;

/// Unified codec for all consensus request-response messages.
/// Supports both initial transaction relay and PBFT vote propagation.
#[derive(Clone, Debug, Default)]
pub struct ConsensusCodec;

// --- Request types ---

/// Unified request enum — the `#[serde(tag = "type")]` adds a "type" field
/// so the receiver can deserialize into the correct variant.
#[derive(Serialize, Deserialize, Clone, Debug)]
#[serde(tag = "type")]
pub enum ConsensusRequest {
    /// Initial transaction relay to validators (replaces gossipsub broadcast).
    #[serde(rename = "tx")]
    TxRelay {
        tx_type: String,
        tx_data_json: String,
        from_node: String,
        signature: String,
    },
    /// PBFT vote/phase message sent directly between committee validators.
    #[serde(rename = "pbft")]
    PbftVote {
        /// Protobuf-encoded PbftMessage as base64 string.
        pbft_message_b64: String,
        phase: i32,
        tx_hash: String,
    },
    /// Direct peer announcement to bypass gossipsub mesh formation delays.
    #[serde(rename = "announce")]
    PeerAnnounce {
        announce_json: String,
    },
}

// --- Old types kept for backward compatibility in swarm_loop.rs references ---
// (will be removed after full transition)

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

// --- Response types ---

/// Unified response enum.
#[derive(Serialize, Deserialize, Clone, Debug)]
#[serde(tag = "type")]
pub enum ConsensusResponse {
    /// Response to a TxRelay request.
    #[serde(rename = "tx_ack")]
    TxAck { accepted: bool, reason: String },
    #[serde(rename = "pbft_ack")]
    PbftAck { received: bool },
    /// Response to a PeerAnnounce request.
    #[serde(rename = "announce_ack")]
    PeerAnnounceAck { received: bool },
}

#[async_trait::async_trait]
impl RrCodec for ConsensusCodec {
    type Protocol = String;
    type Request = ConsensusRequest;
    type Response = ConsensusResponse;

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
    pub request_response: request_response::Behaviour<ConsensusCodec>,
}
