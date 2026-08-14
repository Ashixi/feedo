use serde::{Deserialize, Serialize};
use std::fmt;
use std::str::FromStr;
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

/// Storage class discriminates data types for quota tracking and future encoding policy.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StorageClass {
    /// HTML/CSS/JS sites — highest priority, indefinite storage
    Site,
    /// Nostr social posts — lowest priority, temporary
    SocialPost,
    /// Nostr profiles — medium priority
    Profile,
    /// Arbitrary files / cloud storage — separate quota, paid
    Blob,
}

impl StorageClass {
    /// Human-readable label used in HTTP headers and JSON fields.
    pub fn as_str(&self) -> &'static str {
        match self {
            StorageClass::Site => "site",
            StorageClass::SocialPost => "social_post",
            StorageClass::Profile => "profile",
            StorageClass::Blob => "blob",
        }
    }
}

impl fmt::Display for StorageClass {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

impl FromStr for StorageClass {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_str() {
            "site" => Ok(StorageClass::Site),
            "social_post" | "socialpost" | "social" | "post" => Ok(StorageClass::SocialPost),
            "profile" => Ok(StorageClass::Profile),
            "blob" | "file" | "object" => Ok(StorageClass::Blob),
            other => Err(format!(
                "Unknown storage class '{}'. Valid: site, social_post, profile, blob",
                other
            )),
        }
    }
}

impl Default for StorageClass {
    fn default() -> Self {
        StorageClass::Blob
    }
}

/// Per-class quota tracking with atomic counters.
struct PerClassQuota {
    max_bytes: u64,
    current_bytes: AtomicU64,
}

impl PerClassQuota {
    fn new(max_bytes: u64) -> Self {
        Self {
            max_bytes,
            current_bytes: AtomicU64::new(0),
        }
    }

    /// Atomically reserve `size` bytes if within limit.
    /// Returns true if reserved, false if would exceed quota.
    fn try_reserve(&self, size: u64) -> bool {
        let mut current = self.current_bytes.load(Ordering::Relaxed);
        loop {
            if current.saturating_add(size) > self.max_bytes {
                return false;
            }
            match self.current_bytes.compare_exchange_weak(
                current,
                current + size,
                Ordering::SeqCst,
                Ordering::Relaxed,
            ) {
                Ok(_) => return true,
                Err(actual) => current = actual,
            }
        }
    }

    /// Release previously reserved bytes (used on delete / GC).
    fn release(&self, size: u64) {
        self.current_bytes.fetch_sub(size.min(self.current_bytes.load(Ordering::Relaxed)), Ordering::SeqCst);
    }

    fn usage(&self) -> (u64, u64) {
        (self.current_bytes.load(Ordering::Relaxed), self.max_bytes)
    }
}

/// Configuration for global storage quota and per-user quota.
#[derive(Debug, Clone)]
pub struct QuotaConfig {
    pub total_max_bytes: u64,
    pub per_user_max_bytes: u64,
}

impl Default for QuotaConfig {
    fn default() -> Self {
        Self {
            total_max_bytes: 70 * 1024 * 1024 * 1024,    // 70 GB (whole node)
            per_user_max_bytes: 10 * 1024 * 1024 * 1024, // 10 GB (per user / DID)
        }
    }
}

impl QuotaConfig {
    /// Read configuration from environment variables:
    /// QUOTA_TOTAL_GB (whole node) and QUOTA_PER_USER_GB (per DID).
    pub fn from_env() -> Self {
        let default = QuotaConfig::default();

        let parse_gb = |var: &str, default: u64| -> u64 {
            std::env::var(var)
                .ok()
                .and_then(|v| v.parse::<f64>().ok())
                .map(|v| (v * 1024.0 * 1024.0 * 1024.0) as u64)
                .unwrap_or(default)
        };

        Self {
            total_max_bytes: parse_gb("QUOTA_TOTAL_GB", default.total_max_bytes),
            per_user_max_bytes: parse_gb("QUOTA_PER_USER_GB", default.per_user_max_bytes),
        }
    }
}

/// Manages storage quota globally and per-user (per DID). Thread-safe — can be shared via Arc.
pub struct StorageQuotaManager {
    global: PerClassQuota,
    per_user_max_bytes: u64,
    per_user: Mutex<HashMap<String, Arc<PerClassQuota>>>,
}

impl StorageQuotaManager {
    pub fn new(config: QuotaConfig) -> Self {
        println!(
            "[Quota] Total Storage Quota: {} GB, Per-user Quota: {} GB",
            config.total_max_bytes / (1024 * 1024 * 1024),
            config.per_user_max_bytes / (1024 * 1024 * 1024),
        );
        Self {
            global: PerClassQuota::new(config.total_max_bytes),
            per_user_max_bytes: config.per_user_max_bytes,
            per_user: Mutex::new(HashMap::new()),
        }
    }

    /// Get (or lazily create) the per-user quota counter for a DID.
    fn per_user_quota(&self, did: &str) -> Arc<PerClassQuota> {
        let mut map = self.per_user.lock().unwrap();
        map.entry(did.to_string())
            .or_insert_with(|| Arc::new(PerClassQuota::new(self.per_user_max_bytes)))
            .clone()
    }

    /// Attempt to reserve `size` bytes (global quota only, backwards-compatible).
    /// Returns Ok(()) if within quota, or Err with a human-readable message.
    pub fn check_and_reserve(&self, class: StorageClass, size: u64) -> Result<(), String> {
        if self.global.try_reserve(size) {
            Ok(())
        } else {
            Err(self.exceeded_message(class, self.global.usage()))
        }
    }

    /// Attempt to reserve `size` bytes for a specific DID, enforcing both the
    /// per-user quota (default 10 GB) and the global node quota.
    pub fn check_and_reserve_for(&self, did: &str, class: StorageClass, size: u64) -> Result<(), String> {
        let user = self.per_user_quota(did);

        // 1. Per-user quota first.
        if !user.try_reserve(size) {
            let (used, max) = user.usage();
            let msg = format!(
                "Per-user storage quota exceeded for {}: {:.2} GB used of {:.2} GB max. \
                 Upload rejected. Free up space or contact support.",
                did,
                used as f64 / (1024.0 * 1024.0 * 1024.0),
                max as f64 / (1024.0 * 1024.0 * 1024.0),
            );
            eprintln!("[Quota] WARNING: {}", msg);
            return Err(msg);
        }

        // 2. Global node quota.
        if !self.global.try_reserve(size) {
            user.release(size); // roll back per-user reservation
            return Err(self.exceeded_message(class, self.global.usage()));
        }

        Ok(())
    }

    fn exceeded_message(&self, class: StorageClass, (used, max): (u64, u64)) -> String {
        let msg = format!(
            "Storage quota exceeded (class '{}'): {:.2} GB used of {:.2} GB max. \
             Upload rejected (backpressure). Consider contacting the node operator.",
            class,
            used as f64 / (1024.0 * 1024.0 * 1024.0),
            max as f64 / (1024.0 * 1024.0 * 1024.0),
        );
        eprintln!("[Quota] WARNING: {}", msg);
        msg
    }

    /// Release previously reserved bytes (called on delete or GC).
    pub fn release(&self, _class: StorageClass, size: u64) {
        self.global.release(size);
    }

    /// Release previously reserved bytes for a specific DID.
    pub fn release_for(&self, did: &str, _class: StorageClass, size: u64) {
        self.global.release(size);
        self.per_user_quota(did).release(size);
    }

    /// Return current usage and max for the whole node.
    pub fn usage(&self) -> (u64, u64) {
        self.global.usage()
    }

    /// Return current usage and max for a specific DID.
    pub fn per_user_usage(&self, did: &str) -> (u64, u64) {
        let map = self.per_user.lock().unwrap();
        map.get(did)
            .map(|q| q.usage())
            .unwrap_or((0, self.per_user_max_bytes))
    }

    /// Return JSON-serialisable snapshot of the global quota.
    pub fn usage_all(&self) -> serde_json::Value {
        let (used, max) = self.global.usage();
        serde_json::json!({
            "global": {
                "used_bytes": used,
                "max_bytes": max,
                "used_gb": format!("{:.2}", used as f64 / (1024.0 * 1024.0 * 1024.0)),
                "max_gb": format!("{:.2}", max as f64 / (1024.0 * 1024.0 * 1024.0)),
            }
        })
    }
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_storage_class_parse() {
        assert_eq!("site".parse::<StorageClass>().unwrap(), StorageClass::Site);
        assert_eq!("Site".parse::<StorageClass>().unwrap(), StorageClass::Site);
        assert_eq!("social_post".parse::<StorageClass>().unwrap(), StorageClass::SocialPost);
        assert_eq!("social".parse::<StorageClass>().unwrap(), StorageClass::SocialPost);
        assert_eq!("profile".parse::<StorageClass>().unwrap(), StorageClass::Profile);
        assert_eq!("blob".parse::<StorageClass>().unwrap(), StorageClass::Blob);
        assert_eq!("file".parse::<StorageClass>().unwrap(), StorageClass::Blob);
        assert!("unknown".parse::<StorageClass>().is_err());
    }

    #[test]
    fn test_storage_class_default() {
        assert_eq!(StorageClass::default(), StorageClass::Blob);
    }

    #[test]
    fn test_quota_reserve_and_release() {
        let mgr = StorageQuotaManager::new(QuotaConfig {
            total_max_bytes: 1000,
            per_user_max_bytes: 1000,
        });

        // Reserve within limit
        assert!(mgr.check_and_reserve(StorageClass::SocialPost, 500).is_ok());
        let (used, max) = mgr.usage();
        assert_eq!(used, 500);
        assert_eq!(max, 1000);

        // Reserve more within limit
        assert!(mgr.check_and_reserve(StorageClass::Blob, 400).is_ok());
        let (used, _) = mgr.usage();
        assert_eq!(used, 900);

        // Exceed limit
        assert!(mgr.check_and_reserve(StorageClass::Site, 200).is_err());
        let (used, _) = mgr.usage();
        assert_eq!(used, 900); // unchanged

        // Release
        mgr.release(StorageClass::SocialPost, 400);
        let (used, _) = mgr.usage();
        assert_eq!(used, 500);
    }

    #[test]
    fn test_usage_all_json() {
        let mgr = StorageQuotaManager::new(QuotaConfig::default());
        let json = mgr.usage_all();
        assert!(json["global"]["used_bytes"].as_u64().is_some());
        assert!(json["global"]["max_bytes"].as_u64().is_some());
        assert!(json["global"]["used_gb"].as_str().is_some());
        assert!(json["global"]["max_gb"].as_str().is_some());
    }

    #[test]
    fn test_per_user_quota() {
        let mgr = StorageQuotaManager::new(QuotaConfig {
            total_max_bytes: 1000 * 1024 * 1024 * 1024,
            per_user_max_bytes: 20,
        });

        // User A: reserve 15 bytes — ok.
        assert!(mgr.check_and_reserve_for("did:feedo:0xAAA", StorageClass::Blob, 15).is_ok());
        // User A: +10 more would exceed 20 — rejected.
        assert!(mgr.check_and_reserve_for("did:feedo:0xAAA", StorageClass::Blob, 10).is_err());
        // User B: independent quota — 15 bytes ok.
        assert!(mgr.check_and_reserve_for("did:feedo:0xBBB", StorageClass::Blob, 15).is_ok());
        // Per-user usage reflects reservations.
        assert_eq!(mgr.per_user_usage("did:feedo:0xAAA"), (15, 20));
        // Release frees per-user quota.
        mgr.release_for("did:feedo:0xAAA", StorageClass::Blob, 15);
        assert_eq!(mgr.per_user_usage("did:feedo:0xAAA").0, 0);
    }
}