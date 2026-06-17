use reqwest::Client;
use secp256k1::{Secp256k1, SecretKey, Message};
use sha2::{Digest, Sha256};
use serde::{Deserialize, Serialize};
use std::time::{SystemTime, UNIX_EPOCH};
use std::str::FromStr;
use std::error::Error;

#[derive(Serialize)]
pub struct PublishPayload {
    pub author: String,
    pub hash_id: String,
    pub content_blob_hash: String,
    pub signature: String,
    pub title: Option<String>,
    pub text: String,
    pub source_type: String,
    pub sequence_number: u32,
}

pub struct FeedoClient {
    api_url: String,
    secret_key: SecretKey,
    public_key_hex: String,
    client: Client,
}

impl FeedoClient {
    pub fn new(private_key_hex: &str, api_url: Option<&str>) -> Result<Self, Box<dyn Error>> {
        let clean_hex = private_key_hex.trim_start_matches("0x");
        let secret_key = SecretKey::from_str(clean_hex)?;
        let secp = Secp256k1::new();
        let public_key = secret_key.public_key(&secp);
        
        Ok(Self {
            api_url: api_url.unwrap_or("http://127.0.0.1:8040").trim_end_matches('/').to_string(),
            secret_key,
            public_key_hex: hex::encode(public_key.serialize()),
            client: Client::new(),
        })
    }

    fn sha256(data: &str) -> String {
        let mut hasher = Sha256::new();
        hasher.update(data.as_bytes());
        hex::encode(hasher.finalize())
    }

    pub async fn publish(&self, content: &str, title: Option<String>, source_type: Option<String>) -> Result<serde_json::Value, Box<dyn Error>> {
        let ts = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis();
        let hash_id = Self::sha256(&format!("{}{}", content, ts));
        let content_blob_hash = Self::sha256(content);

        let secp = Secp256k1::new();
        let msg = Message::from_digest_slice(&hex::decode(&hash_id)?)?;
        let sig = secp.sign_ecdsa(&msg, &self.secret_key);

        let payload = PublishPayload {
            author: self.public_key_hex.clone(),
            hash_id,
            content_blob_hash,
            signature: hex::encode(sig.serialize_compact()),
            title,
            text: content.to_string(),
            source_type: source_type.unwrap_or_else(|| "native".to_string()),
            sequence_number: 1,
        };

        let res = self.client.post(format!("{}/local/publish", self.api_url))
            .json(&payload)
            .send()
            .await?;
            
        let json = res.json::<serde_json::Value>().await?;
        Ok(json)
    }

    pub async fn query(&self, text: &str, federated: bool) -> Result<serde_json::Value, Box<dyn Error>> {
        let mut url = format!("{}/query?text={}", self.api_url, urlencoding::encode(text));
        if federated {
            url.push_str("&federated=true");
        }
        let res = self.client.get(&url).send().await?;
        let json = res.json::<serde_json::Value>().await?;
        Ok(json)
    }
}
