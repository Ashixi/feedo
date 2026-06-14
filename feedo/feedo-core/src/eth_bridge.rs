use ethers::prelude::*;
use std::sync::Arc;
use tokio::time::{sleep, Duration};

pub const FEEDO_CONTRACT_ADDRESS: &str = "0x54dd160Ee32062c37424B58Aef6e3EA02d7326cb";

// Generate the type-safe contract bindings
abigen!(
    FeedoPayment,
    r#"[
        {"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"node","type":"address"},{"indexed":false,"internalType":"uint256","name":"amount","type":"uint256"}],"name":"Claimed","type":"event"},
        {"anonymous":false,"inputs":[{"indexed":false,"internalType":"bytes32","name":"newRoot","type":"bytes32"},{"indexed":false,"internalType":"address","name":"validator","type":"address"}],"name":"MerkleRootUpdated","type":"event"},
        {"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"client","type":"address"},{"indexed":true,"internalType":"bytes32","name":"serviceHash","type":"bytes32"},{"indexed":false,"internalType":"uint256","name":"amount","type":"uint256"}],"name":"PaymentReceived","type":"event"},
        {"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"node","type":"address"},{"indexed":false,"internalType":"uint256","name":"slashedAmount","type":"uint256"}],"name":"Slashed","type":"event"},
        {"inputs":[{"internalType":"uint256","name":"totalEarned","type":"uint256"},{"internalType":"bytes32[]","name":"merkleProof","type":"bytes32[]"}],"name":"claim","outputs":[],"stateMutability":"nonpayable","type":"function"},
        {"inputs":[{"internalType":"address","name":"","type":"address"}],"name":"claimedAmounts","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"}
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

    /// Starts a background worker that periodically checks for new payments
    pub async fn start_event_listener(self: Arc<Self>) {
        println!("Started listening for Polygon Web3 Events on contract: {}", FEEDO_CONTRACT_ADDRESS);
        
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
                        if let Ok(event) = FeedoPaymentEvents::decode_log(&log.into()) {
                            match event {
                                FeedoPaymentEvents::PaymentReceivedFilter(payment) => {
                                    // serviceHash - це наш targetId (ID отримувача)
                                    let target_id_hex = format!("0x{}", hex::encode(payment.service_hash));
                                    
                                    // Конвертуємо WEI у u128 (чи u64). Для простоти ділимо на 10^12 щоб влізло в u64 (μMATIC) або залишаємо U256. 
                                    // Поки що конвертуємо в u64 (обережно з великими сумами).
                                    // 1 MATIC = 10^18 WEI. 
                                    let amount_u64 = payment.amount.as_u64(); // Тимчасово припускаємо невеликі суми < 18 MATIC
                                    
                                    println!("Web3 Deposit: {} sent {} wei for target {}", payment.client, payment.amount, target_id_hex);
                                    
                                    self.ledger.credit(&target_id_hex, amount_u64).await;
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
        let contract = FeedoPayment::new(address, client.clone());

        println!("Started Auto-Claim daemon for node wallet: {:?}", wallet.address());

        loop {
            sleep(Duration::from_secs(3600)).await; // Check every hour
            
            // Integration point for accounting.rs:
            // 1. Fetch `totalEarned` for this node from local SQLite/sled
            // 2. Fetch the corresponding Merkle Proof
            // 3. Call contract.claim()
            
            /*
            let total_earned = U256::from(0); 
            let already_claimed = contract.claimed_amounts(wallet.address()).call().await.unwrap_or(U256::zero());
            let owed = total_earned.saturating_sub(already_claimed);
            
            let threshold = U256::from(5) * U256::exp10(18); // e.g. 5 MATIC
            
            if owed > threshold {
                println!("Auto-claiming {} MATIC", owed);
                let proof: Vec<[u8; 32]> = vec![];
                let tx = contract.claim(total_earned, proof);
                match tx.send().await {
                    Ok(pending_tx) => println!("Claim TX sent: {:?}", pending_tx.tx_hash()),
                    Err(e) => eprintln!("Failed to send claim TX: {}", e),
                }
            }
            */
        }
    }
}
