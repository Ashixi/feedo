use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct DidDocument {
    #[serde(rename = "@context")]
    pub context: Vec<String>,
    pub id: String,
    #[serde(rename = "verificationMethod")]
    pub verification_method: Vec<VerificationMethod>,
    pub authentication: Vec<String>,
    pub service: Vec<ServiceEndpoint>,
    #[serde(rename = "feedoState")]
    pub feedo_state: FeedoState,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct VerificationMethod {
    pub id: String,
    #[serde(rename = "type")]
    pub key_type: String,
    pub controller: String,
    #[serde(rename = "publicKeyMultibase")]
    pub public_key_multibase: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct ServiceEndpoint {
    pub id: String,
    #[serde(rename = "type")]
    pub service_type: String,
    #[serde(rename = "serviceEndpoint")]
    pub service_endpoint: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct FeedoState {
    pub nonce: u64,
    pub balance_credits: u64,
    pub reputation_score: u64,
    pub registered_names: Vec<String>,
    pub created_at: u64,
    pub last_active: u64,
}

impl DidDocument {
    pub fn new(id: String, public_key_multibase: String, timestamp: u64) -> Self {
        let main_key_id = format!("{}#main-key", id);
        
        let verification_method = VerificationMethod {
            id: main_key_id.clone(),
            key_type: "Ed25519VerificationKey2020".to_string(),
            controller: id.clone(),
            public_key_multibase,
        };

        let feedo_state = FeedoState {
            nonce: 0,
            balance_credits: 1000, 
            reputation_score: 0,
            registered_names: Vec::new(),
            created_at: timestamp,
            last_active: timestamp,
        };

        Self {
            context: vec![
                "https://www.w3.org/ns/did/v1".to_string(),
                "https://feedo.network/ns/v1".to_string(),
            ],
            id: id.clone(),
            verification_method: vec![verification_method],
            authentication: vec![main_key_id],
            service: Vec::new(),
            feedo_state,
        }
    }
}

pub fn verify_signature(public_key_hex: &str, payload: &[u8], signature_hex: &str) -> bool {
    use ed25519_dalek::{VerifyingKey, Signature, Verifier};
    
    // Clean hex strings
    let pub_clean = public_key_hex.trim_start_matches("0x").trim_start_matches("z").trim_start_matches("f");
    let sig_clean = signature_hex.trim_start_matches("0x");

    let pub_bytes = match hex::decode(pub_clean) {
        Ok(b) => b,
        Err(_) => return false,
    };
    
    let sig_bytes = match hex::decode(sig_clean) {
        Ok(b) => b,
        Err(_) => return false,
    };

    if pub_bytes.len() != 32 || sig_bytes.len() != 64 {
        return false;
    }

    let verifying_key = match VerifyingKey::try_from(pub_bytes.as_slice()) {
        Ok(k) => k,
        Err(_) => return false,
    };

    let signature = match Signature::from_slice(&sig_bytes) {
        Ok(s) => s,
        Err(_) => return false,
    };

    verifying_key.verify(payload, &signature).is_ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{SigningKey, Signer};
    use rand::rngs::OsRng;

    #[test]
    fn test_verify_signature() {
        let mut csprng = OsRng;
        let signing_key: SigningKey = SigningKey::generate(&mut csprng);
        let pub_key = signing_key.verifying_key();
        
        let message = b"hello feedo";
        let signature = signing_key.sign(message);
        
        let pub_hex = hex::encode(pub_key.as_bytes());
        let sig_hex = hex::encode(signature.to_bytes());
        
        assert!(verify_signature(&pub_hex, message, &sig_hex));
        assert!(!verify_signature(&pub_hex, b"wrong message", &sig_hex));
    }
}
