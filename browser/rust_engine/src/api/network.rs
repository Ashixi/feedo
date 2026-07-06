use libp2p::{
    gossipsub, identify, kad, mdns, request_response,
    swarm::NetworkBehaviour, PeerId,
};
use libp2p::kad::store::{RecordStore, MemoryStore, MemoryStoreConfig, Result as KadResult};
use libp2p::kad::{Record, RecordKey, ProviderRecord};
use reed_solomon_erasure::galois_8::ReedSolomon;
use serde::{Deserialize, Serialize};
use std::{borrow::Cow, env, sync::Arc};
use std::sync::atomic::{AtomicBool, Ordering};
use std::error::Error;

pub const DATA_SHARDS: usize = 30;
pub const PARITY_SHARDS: usize = 15;
pub const TOTAL_SHARDS: usize = DATA_SHARDS + PARITY_SHARDS;

#[derive(Serialize, Deserialize, Debug, Clone)]
pub enum DirectRequest {
    Handshake { challenge: String },
    StoreShard { chunk_key: String, data: Vec<u8> },
    FetchShard { chunk_key: String },
    FetchManifest { file_hash: String },
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub enum DirectResponse {
    HandshakeResponse(Vec<u8>),
    StoreOk,
    ShardData(Option<Vec<u8>>),
    ManifestData(Option<Manifest>),
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct Manifest {
    pub file_hash: String,
    pub size: usize,
    pub shards: std::collections::HashMap<usize, String>,
}

pub fn encode_data(data: &[u8]) -> Result<Vec<Vec<u8>>, Box<dyn Error + Send + Sync>> {
    let rs = ReedSolomon::new(DATA_SHARDS, PARITY_SHARDS).map_err(|e| e.to_string())?;
    let shard_size = (data.len() + DATA_SHARDS - 1) / DATA_SHARDS;
    let mut shards = vec![vec![0u8; shard_size]; TOTAL_SHARDS];

    for i in 0..DATA_SHARDS {
        let start = i * shard_size;
        let end = std::cmp::min(start + shard_size, data.len());
        if end > start {
            shards[i][..end - start].copy_from_slice(&data[start..end]);
        }
    }
    rs.encode(&mut shards).map_err(|e| e.to_string())?;
    Ok(shards)
}

pub fn decode_data(mut shards: Vec<Option<Vec<u8>>>, original_len: usize) -> Result<Vec<u8>, Box<dyn Error + Send + Sync>> {
    let rs = ReedSolomon::new(DATA_SHARDS, PARITY_SHARDS).map_err(|e| e.to_string())?;
    rs.reconstruct(&mut shards).map_err(|e| e.to_string())?;

    let mut result = Vec::with_capacity(original_len);
    for i in 0..DATA_SHARDS {
        if let Some(shard) = &shards[i] {
            result.extend_from_slice(shard);
        }
    }
    result.truncate(original_len);
    Ok(result)
}

pub struct HybridStore {
    mem: MemoryStore,
    db: sled::Db,
    pub storage_full: Arc<AtomicBool>,
}

impl HybridStore {
    pub fn new(peer_id: PeerId, db: sled::Db, storage_full: Arc<AtomicBool>) -> Self {
        let mut config = MemoryStoreConfig::default();
        
        let ram_limit = env::var("DHT_RAM_CACHE_LIMIT")
            .unwrap_or_else(|_| "1000".to_string())
            .parse::<usize>()
            .unwrap_or(1000);
            
        config.max_records = ram_limit;
        
        let mem = MemoryStore::with_config(peer_id, config);
        Self { mem, db, storage_full }
    }
}

impl RecordStore for HybridStore {
    type RecordsIter<'a> = <MemoryStore as RecordStore>::RecordsIter<'a>;
    type ProvidedIter<'a> = <MemoryStore as RecordStore>::ProvidedIter<'a>;

    fn get(&self, k: &RecordKey) -> Option<Cow<'_, Record>> {
        if let Some(rec) = self.mem.get(k) {
            return Some(rec);
        }

        let key_bytes = k.as_ref();
        
        if let Ok(Some(val)) = self.db.get(key_bytes) {
            let record = Record {
                key: k.clone(),
                value: val.to_vec(),
                publisher: None,
                expires: None,
            };
            return Some(Cow::Owned(record));
        }

        None
    }

    fn put(&mut self, r: Record) -> KadResult<()> {
        if self.storage_full.load(Ordering::Relaxed) {
            return Err(libp2p::kad::store::Error::MaxProvidedKeys);
        }

        let _ = self.db.insert(r.key.as_ref(), r.value.clone());
        let _ = self.mem.put(r);
        
        Ok(())
    }

    fn remove(&mut self, k: &RecordKey) {
        let _ = self.db.remove(k.as_ref());
        self.mem.remove(k)
    }

    fn records(&self) -> Self::RecordsIter<'_> { self.mem.records() }
    fn add_provider(&mut self, record: ProviderRecord) -> KadResult<()> { self.mem.add_provider(record) }
    fn providers(&self, key: &RecordKey) -> Vec<ProviderRecord> { self.mem.providers(key) }
    fn provided(&self) -> Self::ProvidedIter<'_> { self.mem.provided() }
    fn remove_provider(&mut self, k: &RecordKey, p: &PeerId) { self.mem.remove_provider(k, p) }
}

#[derive(NetworkBehaviour)]
pub struct StorageBehaviour {
    pub gossipsub: gossipsub::Behaviour,
    pub kademlia: kad::Behaviour<kad::store::MemoryStore>,
    pub identify: identify::Behaviour,
    pub req_resp: request_response::cbor::Behaviour<DirectRequest, DirectResponse>,
    pub mdns: mdns::tokio::Behaviour,
}
