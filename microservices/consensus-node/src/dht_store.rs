use std::borrow::Cow;
use std::time::Instant;
use libp2p::PeerId;
use libp2p::kad::store::{Error, RecordStore, Result};
use libp2p::kad::{ProviderRecord, Record, RecordKey};
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize)]
struct StoredRecord {
    key: Vec<u8>,
    value: Vec<u8>,
    publisher: Option<Vec<u8>>,
}

pub struct SledRecordStore {
    db: sled::Db,
    records_tree: sled::Tree,
    providers_tree: sled::Tree,
}

impl SledRecordStore {
    pub fn new(db: sled::Db) -> Self {
        let records_tree = db.open_tree("kad_records").unwrap();
        let providers_tree = db.open_tree("kad_providers").unwrap();
        Self { db, records_tree, providers_tree }
    }
}

pub struct SledRecordsIter<'a> {
    iter: sled::Iter,
    _marker: std::marker::PhantomData<&'a ()>,
}

impl<'a> Iterator for SledRecordsIter<'a> {
    type Item = Cow<'a, Record>;

    fn next(&mut self) -> Option<Self::Item> {
        for res in &mut self.iter {
            if let Ok((_k, v)) = res {
                if let Ok(stored) = bincode::deserialize::<StoredRecord>(&v) {
                    let publisher = stored.publisher.and_then(|p| PeerId::from_bytes(&p).ok());
                    let rec = Record {
                        key: RecordKey::new(&stored.key),
                        value: stored.value,
                        publisher,
                        expires: None, // Ignore expiration for now
                    };
                    return Some(Cow::Owned(rec));
                }
            }
        }
        None
    }
}

pub struct SledProvidedIter<'a> {
    iter: sled::Iter,
    _marker: std::marker::PhantomData<&'a ()>,
}

impl<'a> Iterator for SledProvidedIter<'a> {
    type Item = Cow<'a, ProviderRecord>;

    fn next(&mut self) -> Option<Self::Item> {
        None
    }
}

impl RecordStore for SledRecordStore {
    type RecordsIter<'a> = SledRecordsIter<'a> where Self: 'a;
    type ProvidedIter<'a> = SledProvidedIter<'a> where Self: 'a;

    fn get(&self, k: &RecordKey) -> Option<Cow<'_, Record>> {
        if let Ok(Some(v)) = self.records_tree.get(k.as_ref()) {
            if let Ok(stored) = bincode::deserialize::<StoredRecord>(&v) {
                let publisher = stored.publisher.and_then(|p| PeerId::from_bytes(&p).ok());
                let rec = Record {
                    key: RecordKey::new(&stored.key),
                    value: stored.value,
                    publisher,
                    expires: None,
                };
                return Some(Cow::Owned(rec));
            }
        }
        None
    }

    fn put(&mut self, r: Record) -> Result<()> {
        let publisher = r.publisher.map(|p| p.to_bytes());
        let stored = StoredRecord {
            key: r.key.as_ref().to_vec(),
            value: r.value,
            publisher,
        };
        if let Ok(v) = bincode::serialize(&stored) {
            let _ = self.records_tree.insert(r.key.as_ref(), v);
        }
        Ok(())
    }

    fn remove(&mut self, k: &RecordKey) {
        let _ = self.records_tree.remove(k.as_ref());
    }

    fn records(&self) -> Self::RecordsIter<'_> {
        SledRecordsIter {
            iter: self.records_tree.iter(),
            _marker: std::marker::PhantomData,
        }
    }

    fn add_provider(&mut self, _record: ProviderRecord) -> Result<()> {
        Ok(())
    }

    fn providers(&self, _key: &RecordKey) -> Vec<ProviderRecord> {
        Vec::new()
    }

    fn provided(&self) -> Self::ProvidedIter<'_> {
        SledProvidedIter {
            iter: self.providers_tree.iter(),
            _marker: std::marker::PhantomData,
        }
    }

    fn remove_provider(&mut self, _k: &RecordKey, _p: &PeerId) {
    }
}
