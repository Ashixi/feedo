use ethers::prelude::*;
use std::sync::Arc;
use tokio::time::{sleep, Duration};

pub const FEEDO_CONTRACT_ADDRESS: &str = "0x6C060F17e3BC6B8BaaE9eb638632Fdc3DfAAc51b";

// Generate the type-safe contract bindings
abigen!(
    PporTreasury,
    r#"[
        {"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"client","type":"address"},{"indexed":true,"internalType":"bytes32","name":"serviceHash","type":"bytes32"},{"indexed":false,"internalType":"uint256","name":"poolAmount","type":"uint256"},{"indexed":false,"internalType":"uint256","name":"protocolFee","type":"uint256"}],"name":"PaymentReceived","type":"event"},
        {"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"user","type":"address"},{"indexed":false,"internalType":"uint256","name":"amount","type":"uint256"},{"indexed":false,"internalType":"uint256","name":"timestamp","type":"uint256"}],"name":"Deposit","type":"event"},
        {"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"node","type":"address"},{"indexed":false,"internalType":"uint256","name":"amount","type":"uint256"}],"name":"NodeRegistered","type":"event"},
        {"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"to","type":"address"},{"indexed":false,"internalType":"uint256","name":"amount","type":"uint256"},{"indexed":false,"internalType":"uint256","name":"nonce","type":"uint256"}],"name":"Withdrawn","type":"event"},
        {"anonymous":false,"inputs":[{"indexed":false,"internalType":"address[]","name":"newCommittee","type":"address[]"},{"indexed":false,"internalType":"uint256","name":"nonce","type":"uint256"}],"name":"CommitteeUpdated","type":"event"},
        {"inputs":[{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"amount","type":"uint256"},{"internalType":"bytes[]","name":"signatures","type":"bytes[]"}],"name":"withdraw","outputs":[],"stateMutability":"nonpayable","type":"function"},
        {"inputs":[],"name":"committee","outputs":[{"internalType":"address[]","name":"","type":"address[]"}],"stateMutability":"view","type":"function"}
    ]"#
);

pub struct Web3Bridge {
    provider: Provider<Http>,
    contract_address: Address,
    ledger: Arc<crate::accounting::Ledger>,
}

impl Web3Bridge {
    pub fn new(rpc_url: &str, ledger: Arc<crate::accounting::Ledger>) -> Result<Self, Box<dyn std::error::Error>> {
        let provider = Provider::<Http>::try_from(rpc_url)?;
        let contract_address = FEEDO_CONTRACT_ADDRESS.parse::<Address>()?;
        
        Ok(Self {
            provider,
            contract_address,
            ledger,
        })
    }

    // fetch_committee() ВИДАЛЕНО — комітет тепер обирається нативно в Rust (ppor.rs)
    // на основі репутації та останньої активності, без залежності від смарт-контракту.
    // Залишено порожній слот для уникнення breaking changes у викликаючому коді.
    /// Starts a background worker that periodically checks for new payments
    pub async fn start_event_listener(self: Arc<Self>) {
        eprintln!("Started listening for Polygon Web3 Events on contract: {}", FEEDO_CONTRACT_ADDRESS);
        
        let mut last_block = self.provider.get_block_number().await.unwrap_or(U64::from(0));

        loop {
            // Polling interval
            sleep(Duration::from_secs(10)).await;
            
            let current_block = match self.provider.get_block_number().await {
                Ok(b) => b,
                Err(e) => {
                    eprintln!("Error fetching block number: {}", e);
                    continue;
                }
            };

            if current_block > last_block {
                let filter = Filter::new()
                    .from_block(last_block + 1)
                    .to_block(current_block)
                    .address(self.contract_address);
                    
                if let Ok(logs) = self.provider.get_logs(&filter).await {
                    for log in logs {
                        // Парсимо лог як PaymentReceivedFilter
                        if let Ok(event) = PporTreasuryEvents::decode_log(&log.into()) {
                            match event {
                                PporTreasuryEvents::DepositFilter(dep) => {
                                    // deposit() — mint side of the bridge. Credit the depositor's own DID.
                                    let did = format!("did:feedo:0x{}", hex::encode(dep.user.as_bytes()));
                                    let amount_u64 = dep.amount.as_u64();
                                    eprintln!("Web3 Deposit: {} deposited {} USDT -> credits {}", dep.user, dep.amount, did);
                                    self.ledger.credit(&did, amount_u64).await;
                                },
                                PporTreasuryEvents::PaymentReceivedFilter(payment) => {
                                    // serviceHash - це наш targetId (ID отримувача)
                                    let did = format!("did:feedo:0x{}", hex::encode(&payment.service_hash[12..]));
                                    
                                    // Конвертуємо USDT (6 decimals зазвичай) у u64
                                    let amount_u64 = payment.pool_amount.as_u64(); 
                                    
                                    eprintln!("Web3 PaymentReceived: {} sent {} USDT (pool) -> credits {}", payment.client, payment.pool_amount, did);
                                    
                                    self.ledger.credit(&did, amount_u64).await;
                                },
                                _ => {}
                            }
                        }
                    }
                }
                last_block = current_block;
            }
        }
    }

    /// Background daemon to claim node's accumulated balance if it exceeds the threshold
    pub async fn start_auto_claim_daemon(rpc_url: String, private_key: String) {
        let provider = Provider::<Http>::try_from(rpc_url).expect("Invalid RPC URL");
        let wallet: LocalWallet = private_key.parse().expect("Invalid private key");
        
        // Ensure wallet uses the correct chain ID (Polygon = 137)
        let chain_id = provider.get_chainid().await.unwrap_or(U256::from(137)).as_u64();
        let wallet = wallet.with_chain_id(chain_id);
        
        let client = Arc::new(SignerMiddleware::new(provider, wallet.clone()));
        let address = FEEDO_CONTRACT_ADDRESS.parse::<Address>().unwrap();
        let _contract = PporTreasury::new(address, client.clone());

        eprintln!("Started Auto-Claim daemon for node wallet: {:?}", wallet.address());

        loop {
            sleep(Duration::from_secs(3600)).await; // Check every hour
            
            // Integration point for accounting.rs:
            // 1. Fetch `totalEarned` for this node from local SQLite/sled
            // 2. Broadcast a P2P request to the PPoR committee for signatures
            // 3. Collect 15+ signatures
            // 4. Call contract.withdraw(address, amount, signatures)
            
            /*
            let threshold = U256::from(50) * U256::exp10(6); // 50 USDT
            
            if owed > threshold {
                eprintln!("Auto-claiming {} USDT", owed);
                // Implementation for collecting signatures over P2P goes here...
            }
            */
        }
    }
}
