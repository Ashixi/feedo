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
}
