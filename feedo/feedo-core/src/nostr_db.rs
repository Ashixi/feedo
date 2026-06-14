use rusqlite::{params, Connection, Result};
use std::sync::{Arc, Mutex};
use std::env;
use std::time::{SystemTime, UNIX_EPOCH};
use serde_json::Value;

pub struct NostrDb {
    conn: Arc<Mutex<Connection>>,
}

impl NostrDb {
    pub fn new() -> Result<Self> {
        let db_path = env::var("NOSTR_DB_PATH").unwrap_or_else(|_| "./nostr_events.db".to_string());
        let conn = Connection::open(&db_path)?;
        let db = Self { conn: Arc::new(Mutex::new(conn)) };
        db.init_db()?;
        Ok(db)
    }

    fn init_db(&self) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        // For development: drop the existing table to apply schema changes easily
        // In production, you would use ALTER TABLE or a migration system.
        conn.execute("DROP TABLE IF EXISTS events", [])?;
        
        conn.execute(
            "CREATE TABLE events (
                id TEXT PRIMARY KEY,
                pubkey TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                kind INTEGER NOT NULL,
                content TEXT NOT NULL,
                sig TEXT NOT NULL,
                tags TEXT NOT NULL,
                expires_at INTEGER,
                d_tag TEXT
            )",
            [],
        )?;
        conn.execute("CREATE INDEX idx_events_pubkey ON events(pubkey)", [])?;
        conn.execute("CREATE INDEX idx_events_kind ON events(kind)", [])?;
        conn.execute("CREATE INDEX idx_events_created_at ON events(created_at)", [])?;
        conn.execute("CREATE INDEX idx_events_d_tag ON events(d_tag)", [])?;
        Ok(())
    }

    pub fn delete_expired_events(&self) -> Result<usize> {
        let conn = self.conn.lock().unwrap();
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs() as i64;
        conn.execute("DELETE FROM events WHERE expires_at IS NOT NULL AND expires_at <= ?", params![now])
    }

    pub fn insert_event(
        &self,
        id: &str,
        pubkey: &str,
        created_at: u64,
        kind: u64,
        content: &str,
        sig: &str,
        tags: &str,
    ) -> Result<()> {
        let mut conn = self.conn.lock().unwrap();
        let tx = conn.transaction()?;

        // Parse tags to extract d_tag, expiration, and e tags (for deletion)
        let tags_json: Vec<Vec<String>> = serde_json::from_str(tags).unwrap_or_else(|_| vec![]);
        let mut expires_at: Option<i64> = None;
        let mut d_tag: Option<String> = None;
        let mut e_tags_to_delete: Vec<String> = Vec::new();

        for tag in &tags_json {
            if tag.len() >= 2 {
                match tag[0].as_str() {
                    "expiration" => {
                        if let Ok(exp) = tag[1].parse::<i64>() {
                            expires_at = Some(exp);
                        }
                    }
                    "d" => {
                        d_tag = Some(tag[1].clone());
                    }
                    "e" => {
                        e_tags_to_delete.push(tag[1].clone());
                    }
                    _ => {}
                }
            }
        }

        // NIP-09: Event Deletion (kind 5)
        if kind == 5 {
            for e_id in e_tags_to_delete {
                // Delete the targeted event ONLY IF the pubkey matches
                tx.execute(
                    "DELETE FROM events WHERE id = ? AND pubkey = ?",
                    params![e_id, pubkey],
                )?;
            }
        }

        // Replaceable events: NIP-16 & NIP-33
        // Check if there's already a newer event that replaces this one
        let mut should_insert = true;
        let is_replaceable = kind == 0 || kind == 3 || (10000 <= kind && kind < 20000);
        let is_parameterized = 30000 <= kind && kind < 40000;

        if is_replaceable {
            let newer_count: i64 = tx.query_row(
                "SELECT COUNT(*) FROM events WHERE pubkey = ? AND kind = ? AND created_at >= ?",
                params![pubkey, kind, created_at],
                |row| row.get(0),
            ).unwrap_or(0);
            
            if newer_count > 0 {
                should_insert = false;
            } else {
                tx.execute(
                    "DELETE FROM events WHERE pubkey = ? AND kind = ?",
                    params![pubkey, kind],
                )?;
            }
        } else if is_parameterized {
            let d_val = d_tag.as_deref().unwrap_or("");
            let newer_count: i64 = tx.query_row(
                "SELECT COUNT(*) FROM events WHERE pubkey = ? AND kind = ? AND (d_tag = ? OR (d_tag IS NULL AND ? = '')) AND created_at >= ?",
                params![pubkey, kind, d_val, d_val, created_at],
                |row| row.get(0),
            ).unwrap_or(0);
            
            if newer_count > 0 {
                should_insert = false;
            } else {
                tx.execute(
                    "DELETE FROM events WHERE pubkey = ? AND kind = ? AND (d_tag = ? OR (d_tag IS NULL AND ? = ''))",
                    params![pubkey, kind, d_val, d_val],
                )?;
            }
        }

        if should_insert {
            tx.execute(
                "INSERT OR IGNORE INTO events (id, pubkey, created_at, kind, content, sig, tags, expires_at, d_tag)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
                params![id, pubkey, created_at, kind, content, sig, tags, expires_at, d_tag],
            )?;
        }

        tx.commit()?;
        Ok(())
    }

    pub fn query_events(&self, filter: &Value) -> Result<Vec<Value>> {
        let conn = self.conn.lock().unwrap();
        let mut query = "SELECT id, pubkey, created_at, kind, content, sig, tags FROM events WHERE 1=1".to_string();
        let mut params_vec: Vec<Box<dyn rusqlite::ToSql>> = Vec::new();

        // NIP-40: Expiration - filter out expired events
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs() as i64;
        query.push_str(" AND (expires_at IS NULL OR expires_at > ?)");
        params_vec.push(Box::new(now));

        if let Some(ids) = filter["ids"].as_array() {
            if !ids.is_empty() {
                let placeholders: Vec<String> = ids.iter().map(|_| "?".to_string()).collect();
                query.push_str(&format!(" AND id IN ({})", placeholders.join(", ")));
                for id in ids {
                    if let Some(i) = id.as_str() {
                        params_vec.push(Box::new(i.to_string()));
                    }
                }
            }
        }

        if let Some(authors) = filter["authors"].as_array() {
            if !authors.is_empty() {
                let placeholders: Vec<String> = authors.iter().map(|_| "?".to_string()).collect();
                query.push_str(&format!(" AND pubkey IN ({})", placeholders.join(", ")));
                for author in authors {
                    if let Some(a) = author.as_str() {
                        params_vec.push(Box::new(a.to_string()));
                    }
                }
            }
        }

        if let Some(kinds) = filter["kinds"].as_array() {
            if !kinds.is_empty() {
                let placeholders: Vec<String> = kinds.iter().map(|_| "?".to_string()).collect();
                query.push_str(&format!(" AND kind IN ({})", placeholders.join(", ")));
                for kind in kinds {
                    if let Some(k) = kind.as_u64() {
                        params_vec.push(Box::new(k as i64));
                    }
                }
            }
        }

        if let Some(since) = filter["since"].as_u64() {
            query.push_str(" AND created_at >= ?");
            params_vec.push(Box::new(since as i64));
        }

        if let Some(until) = filter["until"].as_u64() {
            query.push_str(" AND created_at <= ?");
            params_vec.push(Box::new(until as i64));
        }

        // NIP-33 and other tag queries
        // Filter keys starting with '#'
        if let Some(obj) = filter.as_object() {
            for (key, val) in obj.iter() {
                if key.starts_with('#') && val.is_array() {
                    let tag_name = &key[1..];
                    if let Some(arr) = val.as_array() {
                        if !arr.is_empty() {
                            // Using a simple LIKE check for tags. In a production DB you would use a JSON1 extension or a separate tags table.
                            let mut tag_conds = Vec::new();
                            for tag_val in arr {
                                if let Some(v) = tag_val.as_str() {
                                    // Search for ["tag_name", "value" pattern roughly
                                    let like_pattern = format!("%[\"{}\",\"{}\"%", tag_name, v);
                                    tag_conds.push("tags LIKE ?".to_string());
                                    params_vec.push(Box::new(like_pattern));
                                }
                            }
                            if !tag_conds.is_empty() {
                                query.push_str(&format!(" AND ({})", tag_conds.join(" OR ")));
                            }
                        }
                    }
                }
            }
        }

        query.push_str(" ORDER BY created_at DESC");

        let limit = filter["limit"].as_u64().unwrap_or(100).min(500);
        query.push_str(" LIMIT ?");
        params_vec.push(Box::new(limit as i64));

        let sql_params: Vec<&dyn rusqlite::ToSql> = params_vec.iter().map(|p| p.as_ref()).collect();

        let mut stmt = conn.prepare(&query)?;
        let rows = stmt.query_map(&sql_params[..], |row| {
            let id: String = row.get(0)?;
            let pubkey: String = row.get(1)?;
            let created_at: i64 = row.get(2)?;
            let kind: i64 = row.get(3)?;
            let content: String = row.get(4)?;
            let sig: String = row.get(5)?;
            let tags_str: String = row.get(6)?;

            let tags_json: Vec<Value> = serde_json::from_str(&tags_str).unwrap_or_else(|_| vec![]);

            Ok(serde_json::json!({
                "id": id,
                "pubkey": pubkey,
                "created_at": created_at as u64,
                "kind": kind as u64,
                "content": content,
                "sig": sig,
                "tags": tags_json
            }))
        })?;

        let mut events = Vec::new();
        for row in rows {
            if let Ok(event) = row {
                events.push(event);
            }
        }

        Ok(events)
    }
}
