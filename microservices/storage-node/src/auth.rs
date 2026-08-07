use axum::{
    async_trait,
    extract::FromRequestParts,
    http::{request::Parts, StatusCode},
};
use ethers::core::types::{Signature, H160};
use ethers::utils::hash_message;
use std::str::FromStr;
use std::time::{SystemTime, UNIX_EPOCH};

pub struct FeedoAuth {
    pub did: String,
}

#[async_trait]
impl<S> FromRequestParts<S> for FeedoAuth
where
    S: Send + Sync,
{
    type Rejection = (StatusCode, String);

    async fn from_request_parts(parts: &mut Parts, _state: &S) -> Result<Self, Self::Rejection> {
        let did = parts
            .headers
            .get("X-Feedo-DID")
            .and_then(|h| h.to_str().ok())
            .ok_or((StatusCode::UNAUTHORIZED, "Missing X-Feedo-DID".to_string()))?;

        let timestamp_str = parts
            .headers
            .get("X-Feedo-Timestamp")
            .and_then(|h| h.to_str().ok())
            .ok_or((StatusCode::UNAUTHORIZED, "Missing X-Feedo-Timestamp".to_string()))?;

        let signature_hex = parts
            .headers
            .get("X-Feedo-Signature")
            .and_then(|h| h.to_str().ok())
            .ok_or((StatusCode::UNAUTHORIZED, "Missing X-Feedo-Signature".to_string()))?;

        // 1. Time check
        let timestamp_ms: u64 = timestamp_str
            .parse()
            .map_err(|_| (StatusCode::BAD_REQUEST, "Invalid timestamp format".to_string()))?;

        let current_time_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;

        if (current_time_ms as i64 - timestamp_ms as i64).abs() > 5 * 60 * 1000 {
            return Err((StatusCode::UNAUTHORIZED, "Timestamp expired".to_string()));
        }

        // 2. Reconstruct payload
        let method = parts.method.as_str();
        let path = parts.uri.path();
        let payload = format!("FeedoAction:{}:{}:{}", method, path, timestamp_str);

        // 3. Recover address
        let sig_result = if signature_hex.starts_with("0x") {
            signature_hex.parse::<Signature>()
        } else {
            format!("0x{}", signature_hex).parse::<Signature>()
        };

        let signature = sig_result.map_err(|e| {
            (StatusCode::UNAUTHORIZED, format!("Invalid signature format: {:?}", e))
        })?;

        let message_hash = hash_message(payload.as_bytes());
        let recovered = signature
            .recover(message_hash)
            .map_err(|e| (StatusCode::UNAUTHORIZED, format!("Signature recovery failed: {:?}", e)))?;

        // 4. Match with DID
        if !did.starts_with("did:feedo:") {
            return Err((StatusCode::BAD_REQUEST, "Invalid DID format".to_string()));
        }

        let did_address_str = &did["did:feedo:".len()..];
        let clean_addr = did_address_str.trim_start_matches("0x");
        let expected = H160::from_str(clean_addr)
            .map_err(|_| (StatusCode::BAD_REQUEST, "Invalid address in DID".to_string()))?;

        if recovered != expected {
            return Err((StatusCode::UNAUTHORIZED, "Signature does not match DID".to_string()));
        }

        // 5. Consensus check
        let consensus_url = std::env::var("CONSENSUS_NODE_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:3000".to_string());
        
        let client = reqwest::Client::new();
        let correct_did_id = format!("did:feedo:0x{}", clean_addr);
        let check_url = format!("{}/did/{}/balance", consensus_url, correct_did_id);
        
        let res = client.get(&check_url).send().await.map_err(|e| {
            (StatusCode::INTERNAL_SERVER_ERROR, format!("Consensus check failed: {}", e))
        })?;

        if !res.status().is_success() {
            return Err((StatusCode::UNAUTHORIZED, "DID not registered".to_string()));
        }

        let body: serde_json::Value = res.json().await.map_err(|_| {
            (StatusCode::INTERNAL_SERVER_ERROR, "Invalid JSON from consensus".to_string())
        })?;

        if body.is_null() {
            return Err((StatusCode::UNAUTHORIZED, "DID not registered in Consensus Node".to_string()));
        }

        Ok(FeedoAuth { did: did.to_string() })
    }
}
