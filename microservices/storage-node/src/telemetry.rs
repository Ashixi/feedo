use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TelemetryStats {
    #[serde(default)]
    pub storage_used_bytes: u64,
    #[serde(default)]
    pub total_requests: u64,
    #[serde(default)]
    pub vectors_processed: u64,
    #[serde(default)]
    pub pbft_votes_processed: u64,
    #[serde(default)]
    pub blocks_finalized: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TelemetryReport {
    pub node_id: String,
    pub node_type: String, // "storage", "consensus", "search"
    pub timestamp: u64,
    pub stats: TelemetryStats,
}
