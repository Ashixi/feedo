use rusqlite::{params, Connection, Result};
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

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
                cid TEXT
            )",
            [],
        )?;
        
        // Спроба додати колонку, якщо база була створена раніше.
        let _ = conn.execute("ALTER TABLE name_registry ADD COLUMN cid TEXT", []);

        Ok(Self {
            conn: Arc::new(Mutex::new(conn)),
        })
    }

    pub fn insert_name(&self, name: &str, did: &str, public_key: &str) -> Result<()> {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs() as i64;

        let conn = self.conn.lock().unwrap();
        conn.execute(
            "INSERT OR REPLACE INTO name_registry (name, did, public_key, timestamp) VALUES (?1, ?2, ?3, ?4)",
            params![name, did, public_key, timestamp],
        )?;

        Ok(())
    }

    pub fn update_cid(&self, name: &str, cid: &str) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "UPDATE name_registry SET cid = ?1 WHERE name = ?2",
            params![cid, name],
        )?;
        Ok(())
    }

    pub fn resolve_name(&self, name: &str) -> Result<Option<(String, Option<String>)>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare("SELECT did, cid FROM name_registry WHERE name = ?1")?;
        
        let mut rows = stmt.query(params![name])?;
        
        if let Some(row) = rows.next()? {
            let did: String = row.get(0)?;
            let cid: Option<String> = row.get(1)?;
            Ok(Some((did, cid)))
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

    pub fn get_all_records(&self) -> Result<Vec<(String, String, Option<String>)>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare("SELECT name, did, cid FROM name_registry")?;
        
        let rows = stmt.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, Option<String>>(2)?,
            ))
        })?;
        
        let mut records = Vec::new();
        for row in rows {
            records.push(row?);
        }
        
        Ok(records)
    }
}
