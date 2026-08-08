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
            eprintln!("ECDSA signature parse error: {:?}", e);
            return false;
        }
    };

    // Ethereum prefix hashing (EIP-191): "\x19Ethereum Signed Message:\n{len}{msg}"
    let message_hash = hash_message(payload);

    let recovered = match signature.recover(message_hash) {
        Ok(addr) => addr,
        Err(e) => {
            eprintln!("ECDSA signature recovery error: {:?}", e);
            return false;
        }
    };

    let clean_addr = address_hex.trim_start_matches("0x");
    let expected = match H160::from_str(clean_addr) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("Address parse error: {:?}", e);
            return false;
        }
    };

    let ok = recovered == expected;
    if !ok {
        eprintln!("ECDSA mismatch: recovered={:?}, expected={:?}", recovered, expected);
    }
    ok
}


#[cfg(test)]
mod tests {
    use super::*;
    use secp256k1::{Secp256k1, SecretKey, PublicKey, Message};
    use ethers::utils::keccak256;

    /// Допоміжна функція: генерує secp256k1 ключ, повертає
    /// (Ethereum-адреса, підпис у форматі ethers 65-байт)
    fn sign_ethereum(private_key_hex: &str, payload: &[u8]) -> (String, String) {
        let sk_bytes = hex::decode(private_key_hex).unwrap();
        let sk = SecretKey::from_slice(&sk_bytes).unwrap();
        let secp = Secp256k1::new();
        let pk = PublicKey::from_secret_key(&secp, &sk);

        // Ethereum-адреса = останні 20 байт keccak256(uncompressed pubkey без 04)
        let pubkey_bytes = &pk.serialize_uncompressed()[1..];
        let address = format!("0x{}", hex::encode(&keccak256(pubkey_bytes)[12..]));

        // Ethereum personal_sign (EIP-191)
        let prefix = format!(
            "\x19Ethereum Signed Message:\n{}",
            payload.len()
        );
        let msg_hash = keccak256(
            [prefix.as_bytes(), payload].concat().as_slice(),
        );
        let msg = Message::from_digest_slice(&msg_hash).unwrap();
        let (recovery_id, sig_bytes) = secp.sign_ecdsa_recoverable(&msg, &sk).serialize_compact();

        // ethers очікує формат [r(32), s(32), v(1)] = 65 байт
        let mut full_sig = sig_bytes.to_vec();
        full_sig.push(recovery_id.to_i32() as u8);
        let sig_hex = format!("0x{}", hex::encode(&full_sig));

        (address, sig_hex)
    }

    #[test]
    fn test_verify_signature() {
        // Фіксований приватний ключ для детермінованого тесту
        let sk_hex = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2";
        let message = b"hello feedo";
        
        let (address, sig_hex) = sign_ethereum(sk_hex, message);
        
        // Тест 1: валідний підпис
        assert!(
            verify_signature(&address, message, &sig_hex),
            "Valid signature should pass verification"
        );
        
        // Тест 2: інше повідомлення — має провалитися
        assert!(
            !verify_signature(&address, b"wrong message", &sig_hex),
            "Signature of different message should fail"
        );

        // Тест 3: інша адреса — має провалитися
        let sk2 = "b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3";
        let (addr2, _) = sign_ethereum(sk2, b"unused");
        assert!(
            !verify_signature(&addr2, message, &sig_hex),
            "Signature recovered from different address should fail"
        );
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

    pub fn get_all_documents(&self) -> Vec<DidDocument> {
        let mut docs = Vec::new();
        for item in self.db.scan_prefix("did:") {
            if let Ok((_key, value)) = item {
                if let Ok(doc) = serde_json::from_slice::<DidDocument>(&value) {
                    docs.push(doc);
                }
            }
        }
        docs
    }
}
