use serde::{Deserialize, Serialize};
use sled::Db;
use std::collections::HashMap;
use crate::proto::feedo::CrdtOperation;
use crate::did::verify_signature;

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct LwwEntry {
    pub value: String,
    pub timestamp: u64,
    pub author: String,
    pub is_deleted: bool,
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct LwwMapState {
    pub object_id: String,
    pub entries: HashMap<String, LwwEntry>,
}

pub struct CrdtManager {
    db: Db,
}

impl CrdtManager {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    fn check_acl(object_id: &str, author: &str) -> bool {

        if object_id.contains("did:feedo:") {
            let parts: Vec<&str> = object_id.split('/').collect();
            if let Some(did_part) = parts.first() {
                if did_part.starts_with("did:feedo:") && *did_part != author {
                    return false;
                }
            }
        }
        true
    }

    pub fn process_operation(&self, op: &CrdtOperation) -> Result<bool, String> {
        if !Self::check_acl(&op.object_id, &op.author) {
            return Err("ACL Denied: Author does not own this private object".to_string());
        }
        let msg_to_sign = format!("{}:{}:{}:{}", op.object_id, op.key, op.value, op.timestamp);
        let pub_key_hex = op.author.trim_start_matches("did:feedo:");
        if !verify_signature(pub_key_hex, msg_to_sign.as_bytes(), &op.signature) {
            return Err("Invalid CRDT Operation Signature".to_string());
        }

        let log_key = format!("crdt:log:{}:{}_{}", op.object_id, op.timestamp, op.author);
        let state_key = format!("crdt:state:{}", op.object_id);

        let mut state: LwwMapState = match self.db.get(state_key.as_bytes()) {
            Ok(Some(bytes)) => {
                serde_json::from_slice(&bytes).unwrap_or_else(|_| LwwMapState {
                    object_id: op.object_id.clone(),
                    entries: HashMap::new(),
                })
            }
            _ => LwwMapState {
                object_id: op.object_id.clone(),
                entries: HashMap::new(),
            },
        };

        let mut updated = false;
        let is_deleted = op.operation == "delete";
        
        let should_apply = match state.entries.get(&op.key) {
            Some(existing) => {
                if op.timestamp > existing.timestamp {
                    true
                } else if op.timestamp == existing.timestamp {
                    op.author > existing.author
                } else {
                    false
                }
            }
            None => true,
        };

        if should_apply {
            state.entries.insert(op.key.clone(), LwwEntry {
                value: op.value.clone(),
                timestamp: op.timestamp,
                author: op.author.clone(),
                is_deleted,
            });
            updated = true;

            if let Ok(state_bytes) = serde_json::to_vec(&state) {
                let _ = self.db.insert(state_key.as_bytes(), state_bytes);
            }
        }

        use prost::Message;
        let mut op_bytes = Vec::new();
        op.encode(&mut op_bytes).map_err(|e| e.to_string())?;
        let _ = self.db.insert(log_key.as_bytes(), op_bytes);

        Ok(updated)
    }

    pub fn get_state(&self, object_id: &str) -> Option<LwwMapState> {
        let state_key = format!("crdt:state:{}", object_id);
        if let Ok(Some(bytes)) = self.db.get(state_key.as_bytes()) {
            serde_json::from_slice(&bytes).ok()
        } else {
            None
        }
    }
}
