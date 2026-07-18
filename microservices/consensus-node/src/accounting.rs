use sled::Db;
use std::collections::HashMap;
use rs_merkle::{MerkleTree, Hasher};
use ethers::utils::keccak256;
use ethers::abi::Token;
use std::sync::Arc;
use tokio::sync::Mutex;
use std::str::FromStr;
use ethers::types::Address;

#[derive(Clone)]
pub struct Keccak256Algorithm {}

impl Hasher for Keccak256Algorithm {
    type Hash = [u8; 32];

    fn hash(data: &[u8]) -> [u8; 32] {
        keccak256(data)
    }
}

pub struct Ledger {
    db: Db,
    pub balances: Arc<Mutex<HashMap<String, u64>>>,
    /// Відстежує час останньої активності ноди (wallet -> UNIX timestamp).
    /// Використовується для відбору комітету — ноди без активності виключаються.
    pub last_active: Arc<Mutex<HashMap<String, u64>>>,
}

impl Ledger {
    pub fn new(db: Db) -> Self {
        let balances = Arc::new(Mutex::new(HashMap::new()));
        let last_active = Arc::new(Mutex::new(HashMap::new()));
        Self { db, balances, last_active }
    }

    /// Записує поточний час як останню активність для гаманця.
    pub async fn record_activity(&self, wallet: &str) {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let mut map = self.last_active.lock().await;
        map.insert(wallet.to_string(), now);
    }

    /// Додає зароблені кошти (в центах або WEI) до балансу гаманця
    pub async fn credit(&self, wallet: &str, amount: u64) {
        let mut map = self.balances.lock().await;
        let entry = map.entry(wallet.to_string()).or_insert(0);
        *entry += amount;
        
        let db_key = format!("balance:{}", wallet);
        let _ = self.db.insert(db_key.as_bytes(), &entry.to_be_bytes());
    }

    pub async fn debit(&self, wallet: &str, amount: u64) -> bool {
        let mut map = self.balances.lock().await;
        let entry = map.entry(wallet.to_string()).or_insert(0);
        if *entry >= amount {
            *entry -= amount;
            let db_key = format!("balance:{}", wallet);
            let _ = self.db.insert(db_key.as_bytes(), &entry.to_be_bytes());
            true
        } else {
            false
        }
    }

    /// Отримати поточний накопичений баланс
    pub async fn get_balance(&self, wallet: &str) -> u64 {
        let map = self.balances.lock().await;
        *map.get(wallet).unwrap_or(&0)
    }

    /// Нарахувати грантові кредити на DID. Повертає новий баланс.
    pub async fn claim_grant_credits(&self, did: &str, amount: u64, grant_id: &str) -> u64 {
        self.credit(did, amount).await;
        let balance = self.get_balance(did).await;
        eprintln!(
            "[GRANT] Credited {} to {} from {}: new_balance={}",
            amount, did, grant_id, balance
        );
        balance
    }

    /// Generate a full state snapshot containing balances, merkle root, and metadata.
    /// `names` should be fetched from NameDb::get_all_records_full().
    /// `epoch` is the current epoch number.
    /// `signer` is the wallet address of the validator creating the snapshot.
    /// `secret_key` is the secp256k1 secret key for signing the snapshot.
    pub async fn generate_state_snapshot(
        &self,
        epoch: u64,
        names: Vec<crate::name_db::NameRecord>,
        signer: &str,
        secret_key: Option<&secp256k1::SecretKey>,
    ) -> crate::StateSnapshot {
        let map = self.balances.lock().await;

        // Collect sorted balances
        let mut wallets: Vec<&String> = map.keys().collect();
        wallets.sort();
        let mut balances: Vec<(String, u64)> = Vec::with_capacity(wallets.len());
        let mut leaves: Vec<[u8; 32]> = Vec::new();

        for wallet_str in &wallets {
            let amount = map.get(*wallet_str).unwrap();
            balances.push((wallet_str.to_string(), *amount));

            let addr = Address::from_str(wallet_str).unwrap_or(Address::zero());
            let encoded = ethers::abi::encode(&[
                Token::Address(addr),
                Token::Uint(ethers::types::U256::from(*amount)),
            ]);
            let leaf = keccak256(&keccak256(&encoded));
            leaves.push(leaf);
        }

        let merkle_root = if leaves.is_empty() {
            hex::encode([0u8; 32])
        } else {
            let merkle_tree = MerkleTree::<Keccak256Algorithm>::from_leaves(&leaves);
            hex::encode(merkle_tree.root().unwrap_or([0u8; 32]))
        };

        // Convert NameRecords to NameSnapshotEntries
        let name_entries: Vec<crate::NameSnapshotEntry> = names
            .into_iter()
            .map(|r| crate::NameSnapshotEntry {
                name: r.name,
                did: r.did,
                cid: r.cid,
                gateways: r.gateways.and_then(|j| serde_json::from_str(&j).ok()),
                title: r.title,
                description: r.description,
                icon_cid: r.icon_cid,
                created_at: r.created_at,
                updated_at: r.updated_at,
            })
            .collect();

        let created_at = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs();

        // Sign the snapshot
        let signature = if let Some(sk) = secret_key {
            let secp = secp256k1::Secp256k1::new();
            let payload = format!("{}:{}", epoch, merkle_root);
            let message =
                secp256k1::Message::from_hashed_data::<secp256k1::hashes::sha256::Hash>(
                    payload.as_bytes(),
                );
            let sig = secp.sign_ecdsa(&message, sk);
            hex::encode(sig.serialize_compact())
        } else {
            String::new()
        };

        crate::StateSnapshot {
            epoch,
            balances,
            names: name_entries,
            merkle_root,
            created_at,
            signature,
            signer: signer.to_string(),
        }
    }

    /// Згенерувати Merkle Root поточного стану балансів для PBFT лідера
    pub async fn generate_merkle_root(&self) -> ([u8; 32], MerkleTree<Keccak256Algorithm>) {
        let map = self.balances.lock().await;
        let mut leaves: Vec<[u8; 32]> = Vec::new();

        // Сортуємо ключі для детермінованого дерева (важливо для консенсусу)
        let mut wallets: Vec<&String> = map.keys().collect();
        wallets.sort();

        for wallet_str in wallets {
            let amount = map.get(wallet_str).unwrap();
            
            // В Solidity: keccak256(abi.encode(msg.sender, totalEarned))
            let addr = Address::from_str(wallet_str).unwrap_or(Address::zero());
            let encoded = ethers::abi::encode(&[
                Token::Address(addr),
                Token::Uint(ethers::types::U256::from(*amount)),
            ]);
            
            // Подвійне хешування як захист від second preimage attack (bytes.concat(keccak256(...)))
            let leaf = keccak256(&keccak256(&encoded));
            leaves.push(leaf);
        }

        if leaves.is_empty() {
            // Якщо ще немає балансів, повертаємо нульовий рут
            return ([0u8; 32], MerkleTree::<Keccak256Algorithm>::new());
        }

        let merkle_tree = MerkleTree::<Keccak256Algorithm>::from_leaves(&leaves);
        let root = merkle_tree.root().unwrap_or([0u8; 32]);
        
        (root, merkle_tree)
    }
}