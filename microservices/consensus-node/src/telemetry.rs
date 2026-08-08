use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::time::{SystemTime, UNIX_EPOCH};

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

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AggregatedStats {
    pub total_nodes: usize,
    pub storage_nodes: usize,
    pub consensus_nodes: usize,
    pub search_nodes: usize,
    pub total_storage_used_bytes: u64,
    pub total_requests: u64,
    pub total_vectors_processed: u64,
    pub total_pbft_votes: u64,
    pub total_blocks_finalized: u64,
    pub nodes: Vec<TelemetryReport>,
}

pub struct TelemetryCache {
    pub reports: HashMap<String, TelemetryReport>,
    pub file_path: String,
}

impl TelemetryCache {
    pub fn new(file_path: &str) -> Self {
        let reports = if let Ok(data) = fs::read_to_string(file_path) {
            serde_json::from_str(&data).unwrap_or_default()
        } else {
            HashMap::new()
        };
        Self {
            reports,
            file_path: file_path.to_string(),
        }
    }

    pub fn add_report(&mut self, report: TelemetryReport) {
        self.reports.insert(report.node_id.clone(), report);
    }

    pub fn cleanup_old_reports(&mut self) {
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
        // Remove reports older than 1 hour (3600 seconds)
        self.reports.retain(|_, report| now.saturating_sub(report.timestamp) <= 3600);
    }

    pub fn save(&mut self) {
        self.cleanup_old_reports();
        if let Ok(data) = serde_json::to_string_pretty(&self.reports) {
            let _ = fs::write(&self.file_path, data);
        }
    }

    pub fn aggregate(&self) -> AggregatedStats {
        let mut agg = AggregatedStats {
            total_nodes: self.reports.len(),
            storage_nodes: 0,
            consensus_nodes: 0,
            search_nodes: 0,
            total_storage_used_bytes: 0,
            total_requests: 0,
            total_vectors_processed: 0,
            total_pbft_votes: 0,
            total_blocks_finalized: 0,
            nodes: self.reports.values().cloned().collect(),
        };

        for report in self.reports.values() {
            match report.node_type.as_str() {
                "storage" => agg.storage_nodes += 1,
                "consensus" => agg.consensus_nodes += 1,
                "search" => agg.search_nodes += 1,
                _ => {}
            }

            agg.total_storage_used_bytes += report.stats.storage_used_bytes;
            agg.total_requests += report.stats.total_requests;
            agg.total_vectors_processed += report.stats.vectors_processed;
            agg.total_pbft_votes += report.stats.pbft_votes_processed;
            agg.total_blocks_finalized += report.stats.blocks_finalized;
        }

        agg
    }
}
