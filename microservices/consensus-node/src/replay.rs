//! Replay module — restores local state from DHT snapshots on startup.
//!
//! Two modes:
//! 1. **Snapshot replay**: load latest `/snapshot/{epoch}` from DHT,
//!    restore all balances and names from it.
//! 2. **Legacy DHT replay** (fallback): scan individual `/name/*` and
//!    `/did/*` records from DHT (existing behavior).

use crate::{name_db, did};
use std::sync::Arc;
use tokio::sync::Mutex;

/// Restore local state from a `StateSnapshot` loaded from DHT.
/// This is the fast path — no need to replay individual transactions.
pub async fn replay_from_snapshot(
    snapshot: &crate::StateSnapshot,
    name_db: &Arc<Mutex<name_db::NameDb>>,
    _did_manager: &Arc<Mutex<did::DidManager>>,
    ledger: &Arc<crate::accounting::Ledger>,
) -> Result<(), String> {
    let mut names_restored = 0u64;
    let mut balances_restored = 0u64;

    // Step 1: Restore balances
    for (wallet, balance) in &snapshot.balances {
        // Credit the base amount. If the wallet already has a balance,
        // only set if snapshot is newer (simple: always overwrite for now).
        // We use direct access to avoid debit/credit logic — just set.
        {
            let mut map = ledger.balances.lock().await;
            map.insert(wallet.clone(), *balance);
        }
        balances_restored += 1;
    }

    // Step 2: Restore names
    {
        let db = name_db.lock().await;
        for entry in &snapshot.names {
            let _ = db.insert_name(&entry.name, &entry.did, "");
            if let Some(cid) = &entry.cid {
                let gateways_json = entry.gateways.as_ref()
                    .map(|g| serde_json::to_string(g).unwrap_or_else(|_| "[]".to_string()))
                    .unwrap_or_else(|| "[]".to_string());
                let _ = db.update_cid(&entry.name, cid, &gateways_json);
            }
            // Restore metadata
            let _ = db.update_metadata(&entry.name, &entry.title, &entry.description, &entry.icon_cid);
            names_restored += 1;
        }
    }

    // Step 3: Verify Merkle root (optional but recommended)
    if !snapshot.merkle_root.is_empty() {
        let (actual_root, _) = ledger.generate_merkle_root().await;
        let actual_root_hex = hex::encode(actual_root);
        if actual_root_hex != snapshot.merkle_root {
            eprintln!(
                "[REPLAY] WARNING: Merkle root mismatch! Expected {}, got {}. State may be inconsistent.",
                snapshot.merkle_root,
                actual_root_hex
            );
            // Don't fail — the node can still operate and will sync via normal consensus.
        } else {
            eprintln!("[REPLAY] Merkle root verified successfully");
        }
    }

    eprintln!(
        "[REPLAY] Snapshot replay complete: epoch={}, {} names, {} balances restored",
        snapshot.epoch, names_restored, balances_restored
    );

    Ok(())
}

/// Legacy DHT replay — restores from individual DHT records.
/// (Existing behavior, kept as fallback when no snapshot is available.)
pub async fn replay_from_dht(
    name_db: Arc<Mutex<name_db::NameDb>>,
    did_manager: Arc<Mutex<did::DidManager>>,
    dht_records: Vec<(String, Vec<u8>)>, // key, value pairs from DHT scan
) {
    let mut names_restored = 0u64;
    let mut dids_restored = 0u64;

    for (key, value) in &dht_records {
        if key.starts_with("/name/") || !key.starts_with("/") {
            if let Ok(res) = serde_json::from_slice::<crate::ResolveRes>(value) {
                let db = name_db.lock().await;
                let name = key.trim_start_matches("/name/").to_string();
                if name.is_empty() {
                    continue;
                }
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
            if let Ok(doc) = serde_json::from_slice::<crate::did::DidDocument>(value) {
                let dm = did_manager.lock().await;
                let _ = dm.insert_document(&doc);
                dids_restored += 1;
                eprintln!("[REPLAY] Restored DID: {}", doc.id);
            }
        }
    }

    eprintln!(
        "[REPLAY] Legacy replay complete: {} names, {} DIDs restored",
        names_restored, dids_restored
    );
}

/// Migration helper: upgrade old DHT records (missing epoch/finalized_at) to new format.
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
                res.epoch = Some(0);
                res.finalized_at = Some(now);
                migrated.push((key.clone(), res));
                eprintln!("[MIGRATION] Upgraded record: {}", key);
            }
        }
    }

    eprintln!("[MIGRATION] Migrated {} records to new format", migrated.len());
    migrated
}