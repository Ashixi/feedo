use std::str::FromStr;
use ethers::signers::{LocalWallet, Signer};
use reqwest::Client;

pub async fn router_registration_loop(
    node_type: &str,
    node_address: &str,
    priv_key_hex: &str,
    p2p_addr: &str,
    internal_http: &str,
    public_domain: Option<&str>,
) {
    let router_url = std::env::var("ROUTER_NODE_URL")
        .unwrap_or_else(|_| "https://router.feedo.ink".to_string());
    
    if priv_key_hex.is_empty() || node_address.is_empty() {
        println!("Warning: Missing keys, cannot register with Router Node.");
        return;
    }

    let wallet = match LocalWallet::from_str(priv_key_hex) {
        Ok(w) => w,
        Err(e) => {
            println!("Failed to parse private key for router auth: {}", e);
            return;
        }
    };

    let client = Client::new();

    loop {
        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_millis()
            .to_string();
        let path = "/register";
        let payload = format!("FeedoAction:POST:{}:{}", path, timestamp);

        match wallet.sign_message(payload).await {
            Ok(signature) => {
                let sig_hex = format!("0x{}", hex::encode(signature.to_vec()));
                let body = serde_json::json!({
                    "type": node_type,
                    "p2p_addr": p2p_addr,
                    "internal_http": internal_http,
                    "public_domain": public_domain,
                });

                match client
                    .post(format!("{}{}", router_url, path))
                    .header("X-Feedo-Node-ID", node_address)
                    .header("X-Feedo-Timestamp", &timestamp)
                    .header("X-Feedo-Signature", sig_hex)
                    .json(&body)
                    .send()
                    .await
                {
                    Ok(resp) if resp.status().is_success() => {
                        println!("✅ Successfully registered with Router Node");
                        break;
                    }
                    Ok(resp) => println!("Failed to register with router: {:?}", resp.status()),
                    Err(e) => println!("Network error registering with router: {}", e),
                }
            }
            Err(e) => println!("Failed to sign router registration payload: {}", e),
        }
        tokio::time::sleep(tokio::time::Duration::from_secs(5)).await;
    }

    loop {
        tokio::time::sleep(tokio::time::Duration::from_secs(30)).await;
        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_millis()
            .to_string();
        let path = "/heartbeat";
        let payload = format!("FeedoAction:POST:{}:{}", path, timestamp);

        if let Ok(signature) = wallet.sign_message(payload).await {
            let sig_hex = format!("0x{}", hex::encode(signature.to_vec()));
            let _ = client
                .post(format!("{}{}", router_url, path))
                .header("X-Feedo-Node-ID", node_address)
                .header("X-Feedo-Timestamp", &timestamp)
                .header("X-Feedo-Signature", sig_hex)
                .send()
                .await;
        }
    }
}
