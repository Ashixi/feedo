use serde::{Serialize, Deserialize};
use std::collections::HashMap;
use std::fs;

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct PeerCacheEntry {
    pub peer_id: String,
    pub multiaddrs: Vec<String>,
    pub last_seen_unix: u64,
    pub success_count: u32,
    pub fail_count: u32,
    pub score: f64,
    pub api_url: Option<String>,
}

#[derive(Default, Serialize, Deserialize, Clone)]
pub struct PeerCache {
    pub peers: HashMap<String, PeerCacheEntry>,
}

impl PeerCache {
    pub fn load(path: &str) -> Self {
        if let Ok(s) = fs::read_to_string(path) {
            if let Ok(pc) = serde_json::from_str::<PeerCache>(&s) {
                return pc;
            }
        }
        PeerCache::default()
    }

    pub fn save(&self, path: &str) {
        if let Ok(s) = serde_json::to_string_pretty(self) {
            let _ = fs::write(path, s);
        }
    }

    pub fn add_or_update(&mut self, peer_id: &str, addrs: Vec<String>, success: bool) {
        let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
        let entry = self.peers.entry(peer_id.to_string()).or_insert(PeerCacheEntry {
            peer_id: peer_id.to_string(),
            multiaddrs: vec![],
            last_seen_unix: 0,
            success_count: 0,
            fail_count: 0,
            score: 0.0,
            api_url: None,
        });
        entry.last_seen_unix = now;
        for a in addrs.into_iter() {
            if !entry.multiaddrs.contains(&a) {
                entry.multiaddrs.push(a);
            }
        }
        entry.last_seen_unix = now;
        if success {
            entry.success_count = entry.success_count.saturating_add(1);
            entry.score = (entry.score * 0.8) + 0.2 * (entry.success_count as f64 + 1.0);
        } else {
            entry.fail_count = entry.fail_count.saturating_add(1);
            entry.score = (entry.score * 0.9) - 0.1 * (entry.fail_count as f64 + 1.0);
        }
    }

    pub fn update_api_url(&mut self, peer_id: &str, api_url: String) {
        if let Some(entry) = self.peers.get_mut(peer_id) {
            entry.api_url = Some(api_url);
        } else {
            let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
            self.peers.insert(peer_id.to_string(), PeerCacheEntry {
                peer_id: peer_id.to_string(),
                multiaddrs: vec![],
                last_seen_unix: now,
                success_count: 0,
                fail_count: 0,
                score: 0.0,
                api_url: Some(api_url),
            });
        }
    }

    pub fn top_n_addrs(&self, n: usize) -> Vec<String> {
        let mut v: Vec<&PeerCacheEntry> = self.peers.values().collect();
        v.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));
        let mut addrs = Vec::new();
        for e in v.into_iter().take(n) {
            for a in e.multiaddrs.iter() {
                addrs.push(a.clone());
            }
        }
        addrs
    }

    pub fn gc(&mut self, days: u64) {
        let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
        let ttl = days * 24 * 3600;
        self.peers.retain(|_, e| now.saturating_sub(e.last_seen_unix) <= ttl);
    }
}
