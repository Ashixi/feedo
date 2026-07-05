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
}

impl Ledger {
    pub fn new(db: Db) -> Self {
        let balances = Arc::new(Mutex::new(HashMap::new()));
        Self { db, balances }
    }

    /// Додає зароблені кошти (в центах або WEI) до балансу гаманця
    pub async fn credit(&self, wallet: &str, amount: u64) {
        let mut map = self.balances.lock().await;
        let entry = map.entry(wallet.to_string()).or_insert(0);
        *entry += amount;
        
        let db_key = format!("balance:{}", wallet);
        let _ = self.db.insert(db_key.as_bytes(), &entry.to_be_bytes());
    }

    /// Отримати поточний накопичений баланс
    pub async fn get_balance(&self, wallet: &str) -> u64 {
        let map = self.balances.lock().await;
        *map.get(wallet).unwrap_or(&0)
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
