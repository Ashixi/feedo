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

/// Перевіряє Ethereum ECDSA підпис (EIP-191).
/// address_hex — Ethereum-адреса підписувача (0x...)
/// payload — оригінальні байти повідомлення (без prefix)
/// signature_hex — hex-підпис від ethers::LocalWallet::sign_message (0x{r}{s}{v})
pub fn verify_signature(address_hex: &str, payload: &[u8], signature_hex: &str) -> bool {
    use ethers::core::types::{Signature, H160};
    use ethers::utils::hash_message;
    use std::str::FromStr;

    // Нормалізуємо підпис (ethers повертає його як десяткове число або hex)
    // Формат підпису: "r:s:v" або "0x{130 hex chars}"
    let sig_result = if signature_hex.starts_with("0x") || signature_hex.len() == 130 {
        // hex формат
        let hex_clean = if signature_hex.starts_with("0x") {
            signature_hex.to_string()
        } else {
            format!("0x{}", signature_hex)
        };
        hex_clean.parse::<Signature>()
    } else {
        // десятковий формат (ethers повертає u8 значення як decimal)
        // Пробуємо hex після trim
        format!("0x{}", signature_hex).parse::<Signature>()
    };

    let signature = match sig_result {
        Ok(s) => s,
        Err(e) => {
            println!("ECDSA signature parse error: {:?}", e);
            return false;
        }
    };

    // Ethereum prefix hashing (EIP-191): "\x19Ethereum Signed Message:\n{len}{msg}"
    let message_hash = hash_message(payload);

    let recovered = match signature.recover(message_hash) {
        Ok(addr) => addr,
        Err(e) => {
            println!("ECDSA signature recovery error: {:?}", e);
            return false;
        }
    };

    let clean_addr = address_hex.trim_start_matches("0x");
    let expected = match H160::from_str(clean_addr) {
        Ok(a) => a,
        Err(e) => {
            println!("Address parse error: {:?}", e);
            return false;
        }
    };

    let ok = recovered == expected;
    if !ok {
        println!("ECDSA mismatch: recovered={:?}, expected={:?}", recovered, expected);
    }
    ok
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

pub struct DidManager {
    db: sled::Db,
}

impl DidManager {
    pub fn new(db: sled::Db) -> Self {
        Self { db }
    }

    pub fn get_document(&self, did: &str) -> Option<DidDocument> {
        if let Ok(Some(data)) = self.db.get(format!("did:{}", did).as_bytes()) {
            serde_json::from_slice(&data).ok()
        } else {
            None
        }
    }

    pub fn insert_document(&self, doc: &DidDocument) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        let data = serde_json::to_vec(doc)?;
        self.db.insert(format!("did:{}", doc.id).as_bytes(), data)?;
        Ok(())
    }
}
