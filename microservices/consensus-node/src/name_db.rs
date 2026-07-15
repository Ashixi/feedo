use rusqlite::{params, Connection, Result};
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

/// Full metadata record for a registered name.
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub struct NameRecord {
    pub name: String,
    pub did: String,
    pub public_key: String,
    pub timestamp: i64,
    pub cid: Option<String>,
    pub gateways: Option<String>,
    pub title: Option<String>,
    pub description: Option<String>,
    pub icon_cid: Option<String>,
    pub created_at: Option<i64>,
    pub updated_at: Option<i64>,
}

#[derive(Clone)]
pub struct NameDb {
    conn: Arc<Mutex<Connection>>,
}

impl NameDb {
    pub fn new(db_path: &str) -> Result<Self> {
        let conn = Connection::open(db_path)?;
        
        conn.execute(
            "CREATE TABLE IF NOT EXISTS name_registry (
                name TEXT PRIMARY KEY,
                did TEXT NOT NULL,
                public_key TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                cid TEXT,
                gateways TEXT,
                title TEXT,
                description TEXT,
                icon_cid TEXT,
                created_at INTEGER,
                updated_at INTEGER
            )",
            [],
        )?;
        
        // Спроба додати колонку, якщо база була створена раніше.
        let _ = conn.execute("ALTER TABLE name_registry ADD COLUMN cid TEXT", []);
        let _ = conn.execute("ALTER TABLE name_registry ADD COLUMN gateways TEXT", []);
        let _ = conn.execute("ALTER TABLE name_registry ADD COLUMN title TEXT", []);
        let _ = conn.execute("ALTER TABLE name_registry ADD COLUMN description TEXT", []);
        let _ = conn.execute("ALTER TABLE name_registry ADD COLUMN icon_cid TEXT", []);
        let _ = conn.execute("ALTER TABLE name_registry ADD COLUMN created_at INTEGER", []);
        let _ = conn.execute("ALTER TABLE name_registry ADD COLUMN updated_at INTEGER", []);

        // Grant claims table
        let _ = conn.execute(
            "CREATE TABLE IF NOT EXISTS grant_claims (
                did TEXT NOT NULL,
                grant_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                claimed_at INTEGER NOT NULL,
                tx_hash TEXT,
                PRIMARY KEY (did, grant_id)
            )",
            [],
        );

        Ok(Self {
            conn: Arc::new(Mutex::new(conn)),
        })
    }

    pub fn insert_name(&self, name: &str, did: &str, public_key: &str) -> Result<()> {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs() as i64;

        let conn = self.conn.lock().unwrap();
        conn.execute(
            "INSERT OR REPLACE INTO name_registry (name, did, public_key, timestamp, created_at) VALUES (?1, ?2, ?3, ?4, ?5)",
            params![name, did, public_key, now, now],
        )?;

        Ok(())
    }

    pub fn update_cid(&self, name: &str, cid: &str, gateways_json: &str) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "UPDATE name_registry SET cid = ?1, gateways = ?2 WHERE name = ?3",
            params![cid, gateways_json, name],
        )?;
        Ok(())
    }

    pub fn resolve_name(&self, name: &str) -> Result<Option<(String, Option<String>, Option<String>)>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare("SELECT did, cid, gateways FROM name_registry WHERE name = ?1")?;
        
        let mut rows = stmt.query(params![name])?;
        
        if let Some(row) = rows.next()? {
            let did: String = row.get(0)?;
            let cid: Option<String> = row.get(1)?;
            let gateways: Option<String> = row.get(2)?;
            Ok(Some((did, cid, gateways)))
        } else {
            Ok(None)
        }
    }

    pub fn resolve_cid(&self, cid: &str) -> Result<Option<String>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare("SELECT name FROM name_registry WHERE cid = ?1 LIMIT 1")?;
        
        let mut rows = stmt.query(params![cid])?;
        
        if let Some(row) = rows.next()? {
            let name: String = row.get(0)?;
            Ok(Some(name))
        } else {
            Ok(None)
        }
    }

    pub fn name_exists(&self, name: &str) -> Result<bool> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare("SELECT 1 FROM name_registry WHERE name = ?1 LIMIT 1")?;
        
        let mut rows = stmt.query(params![name])?;
        Ok(rows.next()?.is_some())
    }

    /// Returns all records with full metadata (for state snapshot generation).
    pub fn get_all_records_full(&self) -> Result<Vec<NameRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT name, did, public_key, timestamp, cid, gateways, title, description, icon_cid, created_at, updated_at FROM name_registry"
        )?;

        let rows = stmt.query_map([], |row| {
            Ok(NameRecord {
                name: row.get(0)?,
                did: row.get(1)?,
                public_key: row.get(2)?,
                timestamp: row.get(3)?,
                cid: row.get(4)?,
                gateways: row.get(5)?,
                title: row.get(6)?,
                description: row.get(7)?,
                icon_cid: row.get(8)?,
                created_at: row.get(9)?,
                updated_at: row.get(10)?,
            })
        })?;

        let mut records = Vec::new();
        for row in rows {
            records.push(row?);
        }

        Ok(records)
    }

    pub fn get_all_records(&self) -> Result<Vec<(String, String, Option<String>, Option<String>)>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare("SELECT name, did, cid, gateways FROM name_registry")?;
        
        let rows = stmt.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, Option<String>>(2)?,
                row.get::<_, Option<String>>(3)?,
            ))
        })?;
        
        let mut records = Vec::new();
        for row in rows {
            records.push(row?);
        }
        
        Ok(records)
    }

    pub fn get_names_by_did(&self, did: &str) -> Result<Vec<NameRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT name, did, public_key, timestamp, cid, gateways, title, description, icon_cid, created_at, updated_at FROM name_registry WHERE did = ?1"
        )?;
        
        let rows = stmt.query_map(params![did], |row| {
            Ok(NameRecord {
                name: row.get(0)?,
                did: row.get(1)?,
                public_key: row.get(2)?,
                timestamp: row.get(3)?,
                cid: row.get(4)?,
                gateways: row.get(5)?,
                title: row.get(6)?,
                description: row.get(7)?,
                icon_cid: row.get(8)?,
                created_at: row.get(9)?,
                updated_at: row.get(10)?,
            })
        })?;
        
        let mut records = Vec::new();
        for row in rows {
            records.push(row?);
        }
        
        Ok(records)
    }

    /// Update metadata fields: title, description, icon_cid.
    /// Also updates `updated_at` timestamp.
    pub fn update_metadata(&self, name: &str, title: &Option<String>, description: &Option<String>, icon_cid: &Option<String>) -> Result<()> {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs() as i64;

        let conn = self.conn.lock().unwrap();
        conn.execute(
            "UPDATE name_registry SET title = ?1, description = ?2, icon_cid = ?3, updated_at = ?4 WHERE name = ?5",
            params![title, description, icon_cid, now, name],
        )?;
        Ok(())
    }

    /// Full resolve returning all metadata fields.
    pub fn resolve_name_full(&self, name: &str) -> Result<Option<NameRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT name, did, public_key, timestamp, cid, gateways, title, description, icon_cid, created_at, updated_at FROM name_registry WHERE name = ?1"
        )?;
        
        let mut rows = stmt.query(params![name])?;
        
        if let Some(row) = rows.next()? {
            Ok(Some(NameRecord {
                name: row.get(0)?,
                did: row.get(1)?,
                public_key: row.get(2)?,
                timestamp: row.get(3)?,
                cid: row.get(4)?,
                gateways: row.get(5)?,
                title: row.get(6)?,
                description: row.get(7)?,
                icon_cid: row.get(8)?,
                created_at: row.get(9)?,
                updated_at: row.get(10)?,
            }))
        } else {
            Ok(None)
        }
    }

    // --- Grant Claims ---

    /// Записати факт клейму гранту.
    pub fn insert_grant_claim(
        &self,
        did: &str,
        grant_id: &str,
        amount: u64,
        tx_hash: &str,
    ) -> Result<()> {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs() as i64;

        let conn = self.conn.lock().unwrap();
        conn.execute(
            "INSERT OR IGNORE INTO grant_claims (did, grant_id, amount, claimed_at, tx_hash) VALUES (?1, ?2, ?3, ?4, ?5)",
            params![did, grant_id, amount as i64, now, tx_hash],
        )?;
        Ok(())
    }

    /// Перевірити чи DID уже клеймив цей грант.
    pub fn has_claimed(&self, did: &str, grant_id: &str) -> Result<bool> {
        let conn = self.conn.lock().unwrap();
        let mut stmt =
            conn.prepare("SELECT COUNT(*) FROM grant_claims WHERE did = ?1 AND grant_id = ?2")?;
        let count: i64 = stmt.query_row(params![did, grant_id], |row| row.get(0))?;
        Ok(count > 0)
    }
}
