//! Replay module — restores local state from DHT on startup.
//! Reads DHT keys `/name/*`, `/did/*` and populates local Sled cache.

use crate::{name_db, did};
use std::sync::Arc;
use tokio::sync::Mutex;

/// Restore local name_db and did_manager caches from DHT records.
/// Called once at startup before the HTTP server starts serving requests.
pub async fn replay_from_dht(
    name_db: Arc<Mutex<name_db::NameDb>>,
    did_manager: Arc<Mutex<did::DidManager>>,
    dht_records: Vec<(String, Vec<u8>)>, // key, value pairs from DHT scan
) {
    let mut names_restored = 0u64;
    let mut dids_restored = 0u64;

    for (key, value) in &dht_records {
        if key.starts_with("/name/") || !key.starts_with("/") {
            // It's a name record — parse as ResolveRes
            if let Ok(res) = serde_json::from_slice::<crate::ResolveRes>(value) {
                let db = name_db.lock().await;
                let name = key.trim_start_matches("/name/").to_string();
                if name.is_empty() {
                    continue;
                }
                // Insert into local cache
                let _ = db.insert_name(&name, &res.did, "");
                if let Some(cid) = &res.cid {
                    let gateways_json = res.gateways.as_ref()
                        .map(|g| serde_json::to_string(g).unwrap_or_else(|_| "[]".to_string()))
                        .unwrap_or_else(|| "[]".to_string());
                    let _ = db.update_cid(&name, cid, &gateways_json);
                }
                names_restored += 1;
                eprintln!("[REPLAY] Restored name: {}", name);
            }
        } else if key.starts_with("/did/") {
            // It's a DID record
            if let Ok(doc) = serde_json::from_slice::<crate::did::DidDocument>(value) {
                let dm = did_manager.lock().await;
                let _ = dm.insert_document(&doc);
                dids_restored += 1;
                eprintln!("[REPLAY] Restored DID: {}", doc.id);
            }
        }
    }

    eprintln!(
        "[REPLAY] Replay complete: {} names, {} DIDs restored",
        names_restored, dids_restored
    );
}

/// Migration helper: upgrade old DHT records (missing epoch/finalized_at) to new format.
/// Returns the migrated records ready for DHT republishing.
pub fn migrate_old_records(
    records: Vec<(String, Vec<u8>)>,
) -> Vec<(String, crate::ResolveRes)> {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let mut migrated = Vec::new();

    for (key, value) in &records {
        if let Ok(mut res) = serde_json::from_slice::<crate::ResolveRes>(value) {
            if res.epoch.is_none() || res.finalized_at.is_none() {
                res.epoch = Some(0); // genesis epoch
                res.finalized_at = Some(now);
                migrated.push((key.clone(), res));
                eprintln!("[MIGRATION] Upgraded record: {}", key);
            }
        }
    }

    eprintln!("[MIGRATION] Migrated {} records to new format", migrated.len());
    migrated
}