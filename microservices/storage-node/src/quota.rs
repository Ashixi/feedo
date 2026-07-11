use serde::{Deserialize, Serialize};
use std::fmt;
use std::str::FromStr;
use std::sync::atomic::{AtomicU64, Ordering};

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

/// Configuration for all storage class quotas.
#[derive(Debug, Clone)]
pub struct QuotaConfig {
    pub sites_max_bytes: u64,
    pub blobs_max_bytes: u64,
    pub social_max_bytes: u64,
    pub profiles_max_bytes: u64,
}

impl Default for QuotaConfig {
    fn default() -> Self {
        Self {
            sites_max_bytes: 100 * 1024 * 1024 * 1024,   // 100 GB
            blobs_max_bytes: 1000 * 1024 * 1024 * 1024,  // 1 TB
            social_max_bytes: 500 * 1024 * 1024,          // 500 MB
            profiles_max_bytes: 100 * 1024 * 1024,        // 100 MB
        }
    }
}

impl QuotaConfig {
    /// Read configuration from environment variables:
    ///   QUOTA_SITES_GB, QUOTA_BLOBS_GB, QUOTA_SOCIAL_MB, QUOTA_PROFILES_MB
    pub fn from_env() -> Self {
        let default = QuotaConfig::default();

        let parse_gb = |var: &str, default: u64| -> u64 {
            std::env::var(var)
                .ok()
                .and_then(|v| v.parse::<f64>().ok())
                .map(|v| (v * 1024.0 * 1024.0 * 1024.0) as u64)
                .unwrap_or(default)
        };

        let parse_mb = |var: &str, default: u64| -> u64 {
            std::env::var(var)
                .ok()
                .and_then(|v| v.parse::<f64>().ok())
                .map(|v| (v * 1024.0 * 1024.0) as u64)
                .unwrap_or(default)
        };

        Self {
            sites_max_bytes: parse_gb("QUOTA_SITES_GB", default.sites_max_bytes),
            blobs_max_bytes: parse_gb("QUOTA_BLOBS_GB", default.blobs_max_bytes),
            social_max_bytes: parse_mb("QUOTA_SOCIAL_MB", default.social_max_bytes),
            profiles_max_bytes: parse_mb("QUOTA_PROFILES_MB", default.profiles_max_bytes),
        }
    }
}

/// Manages storage quotas per class. Thread-safe — can be shared via Arc.
pub struct StorageQuotaManager {
    sites: PerClassQuota,
    blobs: PerClassQuota,
    social: PerClassQuota,
    profiles: PerClassQuota,
}

impl StorageQuotaManager {
    pub fn new(config: QuotaConfig) -> Self {
        println!(
            "[Quota] Sites: {} GB, Blobs: {} GB, Social: {} MB, Profiles: {} MB",
            config.sites_max_bytes / (1024 * 1024 * 1024),
            config.blobs_max_bytes / (1024 * 1024 * 1024),
            config.social_max_bytes / (1024 * 1024),
            config.profiles_max_bytes / (1024 * 1024),
        );
        Self {
            sites: PerClassQuota::new(config.sites_max_bytes),
            blobs: PerClassQuota::new(config.blobs_max_bytes),
            social: PerClassQuota::new(config.social_max_bytes),
            profiles: PerClassQuota::new(config.profiles_max_bytes),
        }
    }

    fn quota_for(&self, class: StorageClass) -> &PerClassQuota {
        match class {
            StorageClass::Site => &self.sites,
            StorageClass::Blob => &self.blobs,
            StorageClass::SocialPost => &self.social,
            StorageClass::Profile => &self.profiles,
        }
    }

    /// Attempt to reserve `size` bytes for the given storage class.
    /// Returns Ok(()) if within quota, or Err with a human-readable message.
    pub fn check_and_reserve(&self, class: StorageClass, size: u64) -> Result<(), String> {
        let quota = self.quota_for(class);
        if quota.try_reserve(size) {
            Ok(())
        } else {
            let (used, max) = quota.usage();
            let msg = format!(
                "Storage quota exceeded for class '{}': {:.2} MB used of {:.2} MB max. \
                 Upload rejected (backpressure). Consider contacting the node operator.",
                class,
                used as f64 / (1024.0 * 1024.0),
                max as f64 / (1024.0 * 1024.0),
            );
            eprintln!("[Quota] WARNING: {}", msg);
            Err(msg)
        }
    }

    /// Release previously reserved bytes (called on delete or GC).
    pub fn release(&self, class: StorageClass, size: u64) {
        self.quota_for(class).release(size);
    }

    /// Return current usage and max for a single class.
    pub fn usage(&self, class: StorageClass) -> (u64, u64) {
        self.quota_for(class).usage()
    }

    /// Return JSON-serialisable snapshot of all quotas.
    pub fn usage_all(&self) -> serde_json::Value {
        let (su, sm) = self.sites.usage();
        let (bu, bm) = self.blobs.usage();
        let (sou, som) = self.social.usage();
        let (pu, pm) = self.profiles.usage();
        serde_json::json!({
            "site": {
                "used_bytes": su,
                "max_bytes": sm,
                "used_mb": format!("{:.2}", su as f64 / (1024.0 * 1024.0)),
                "max_mb": format!("{:.2}", sm as f64 / (1024.0 * 1024.0)),
            },
            "blob": {
                "used_bytes": bu,
                "max_bytes": bm,
                "used_mb": format!("{:.2}", bu as f64 / (1024.0 * 1024.0)),
                "max_mb": format!("{:.2}", bm as f64 / (1024.0 * 1024.0)),
            },
            "social_post": {
                "used_bytes": sou,
                "max_bytes": som,
                "used_mb": format!("{:.2}", sou as f64 / (1024.0 * 1024.0)),
                "max_mb": format!("{:.2}", som as f64 / (1024.0 * 1024.0)),
            },
            "profile": {
                "used_bytes": pu,
                "max_bytes": pm,
                "used_mb": format!("{:.2}", pu as f64 / (1024.0 * 1024.0)),
                "max_mb": format!("{:.2}", pm as f64 / (1024.0 * 1024.0)),
            },
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
            social_max_bytes: 1000,
            ..Default::default()
        });

        // Reserve within limit
        assert!(mgr.check_and_reserve(StorageClass::SocialPost, 500).is_ok());
        let (used, max) = mgr.usage(StorageClass::SocialPost);
        assert_eq!(used, 500);
        assert_eq!(max, 1000);

        // Reserve more within limit
        assert!(mgr.check_and_reserve(StorageClass::SocialPost, 400).is_ok());
        let (used, _) = mgr.usage(StorageClass::SocialPost);
        assert_eq!(used, 900);

        // Exceed limit
        assert!(mgr.check_and_reserve(StorageClass::SocialPost, 200).is_err());
        let (used, _) = mgr.usage(StorageClass::SocialPost);
        assert_eq!(used, 900); // unchanged

        // Release
        mgr.release(StorageClass::SocialPost, 400);
        let (used, _) = mgr.usage(StorageClass::SocialPost);
        assert_eq!(used, 500);
    }

    #[test]
    fn test_quota_independent_classes() {
        let mgr = StorageQuotaManager::new(QuotaConfig {
            social_max_bytes: 1000,
            sites_max_bytes: 2000,
            ..Default::default()
        });

        // Fill social quota
        assert!(mgr.check_and_reserve(StorageClass::SocialPost, 1000).is_ok());
        assert!(mgr.check_and_reserve(StorageClass::SocialPost, 1).is_err());

        // Sites still work independently
        assert!(mgr.check_and_reserve(StorageClass::Site, 2000).is_ok());
        assert!(mgr.check_and_reserve(StorageClass::Site, 1).is_err());
    }

    #[test]
    fn test_usage_all_json() {
        let mgr = StorageQuotaManager::new(QuotaConfig::default());
        let json = mgr.usage_all();
        assert!(json["site"]["used_bytes"].as_u64().is_some());
        assert!(json["blob"]["max_bytes"].as_u64().is_some());
        assert!(json["social_post"]["used_mb"].as_str().is_some());
        assert!(json["profile"]["max_mb"].as_str().is_some());
    }
}