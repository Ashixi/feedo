use ethers::signers::{LocalWallet, Signer};
use ethers::core::rand::thread_rng;
use std::sync::{Mutex, OnceLock};
use std::path::Path;
use std::str::FromStr;

static CURRENT_WALLET: OnceLock<Mutex<Option<LocalWallet>>> = OnceLock::new();

fn get_wallet_lock() -> &'static Mutex<Option<LocalWallet>> {
    CURRENT_WALLET.get_or_init(|| Mutex::new(None))
}

#[derive(serde::Serialize)]
pub struct WalletInfo {
    pub address: String,
    pub did: String,
}

pub fn generate_wallet() -> Result<String, String> {
    let wallet = LocalWallet::new(&mut thread_rng());
    let address = format!("{:?}", wallet.address());
    let did = format!("did:feedo:{}", address.trim_start_matches("0x"));
    
    *get_wallet_lock().lock().unwrap() = Some(wallet);
    
    let info = WalletInfo { address, did };
    serde_json::to_string(&info).map_err(|e| e.to_string())
}

pub fn import_wallet(private_key_hex: String) -> Result<String, String> {
    let wallet = LocalWallet::from_str(&private_key_hex).map_err(|e| e.to_string())?;
    let address = format!("{:?}", wallet.address());
    let did = format!("did:feedo:{}", address.trim_start_matches("0x"));
    
    *get_wallet_lock().lock().unwrap() = Some(wallet);
    
    let info = WalletInfo { address, did };
    serde_json::to_string(&info).map_err(|e| e.to_string())
}

pub fn encrypt_and_save_wallet(password: String, dir_path: String) -> Result<String, String> {
    let wallet_lock = get_wallet_lock().lock().unwrap();
    let wallet = wallet_lock.as_ref().ok_or("No wallet loaded")?;
    
    let path = Path::new(&dir_path);
    if !path.exists() {
        std::fs::create_dir_all(path).map_err(|e| e.to_string())?;
    }
    
    let pk_bytes = wallet.signer().to_bytes();
    let uuid = eth_keystore::encrypt_key(&dir_path, &mut thread_rng(), pk_bytes, &password, None)
        .map_err(|e| e.to_string())?;
    
    let key_path = path.join(uuid);
    Ok(key_path.to_string_lossy().into_owned())
}

pub fn load_and_decrypt_wallet(password: String, file_path: String) -> Result<String, String> {
    let wallet = LocalWallet::decrypt_keystore(&file_path, &password)
        .map_err(|e| e.to_string())?;
        
    let address = format!("{:?}", wallet.address());
    let did = format!("did:feedo:{}", address.trim_start_matches("0x"));
    
    *get_wallet_lock().lock().unwrap() = Some(wallet);
    
    let info = WalletInfo { address, did };
    serde_json::to_string(&info).map_err(|e| e.to_string())
}

pub async fn sign_message(message: String) -> Result<String, String> {
    let wallet = {
        let wallet_lock = get_wallet_lock().lock().unwrap();
        wallet_lock.as_ref().ok_or("No wallet loaded")?.clone()
    };
    
    let signature = wallet.sign_message(message.as_bytes()).await
        .map_err(|e| e.to_string())?;
        
    // Serialize as 65-byte hex (r || s || v) for consensus node verification.
    // ethers sign_message already returns v ∈ {27, 28} (Ethereum EIP-191 standard).
    // No "0x" prefix — consensus's verify_signature adds it internally.
    Ok(hex::encode(signature.to_vec()))
}

pub fn get_did() -> Result<String, String> {
    let wallet_lock = get_wallet_lock().lock().unwrap();
    let wallet = wallet_lock.as_ref().ok_or("No wallet loaded")?;
    
    let address = format!("{:?}", wallet.address());
    Ok(format!("did:feedo:{}", address.trim_start_matches("0x")))
}

pub fn get_address() -> Result<String, String> {
    let wallet_lock = get_wallet_lock().lock().unwrap();
    let wallet = wallet_lock.as_ref().ok_or("No wallet loaded")?;
    
    Ok(format!("{:?}", wallet.address()))
}
