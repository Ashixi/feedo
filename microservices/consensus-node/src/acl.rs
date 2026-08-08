use sled::Db;
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct FileAccessGrant {
    pub file_hash: String,
    pub grantee_did: String,
    pub encrypted_symmetric_key: String,
}

pub struct AclManager {
    db: Db,
}

impl AclManager {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    pub fn grant_access(&self, file_hash: &str, grantee_did: &str, encrypted_key: &str) -> Result<(), sled::Error> {
        let db_key = format!("acl:{}:{}", file_hash, grantee_did);
        self.db.insert(db_key.as_bytes(), encrypted_key.as_bytes())?;
        Ok(())
    }

    pub fn get_encrypted_key(&self, file_hash: &str, grantee_did: &str) -> Option<String> {
        let db_key = format!("acl:{}:{}", file_hash, grantee_did);
        if let Ok(Some(data)) = self.db.get(db_key.as_bytes()) {
            if let Ok(key) = String::from_utf8(data.to_vec()) {
                return Some(key);
            }
        }
        None
    }
    pub fn get_all_grants(&self) -> Vec<(String, String, String)> {
        let mut grants = Vec::new();
        for item in self.db.scan_prefix("acl:") {
            if let Ok((key, value)) = item {
                if let (Ok(key_str), Ok(val_str)) = (String::from_utf8(key.to_vec()), String::from_utf8(value.to_vec())) {
                    let parts: Vec<&str> = key_str.split(':').collect();
                    if parts.len() == 3 {
                        grants.push((parts[1].to_string(), parts[2].to_string(), val_str));
                    }
                }
            }
        }
        grants
    }
}
