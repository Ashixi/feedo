use std::collections::HashSet;
use secp256k1::{Secp256k1, Message, ecdsa};
use ethers::utils::keccak256;

/// Перевіряє чи має право signer створити грант.
///
/// Поточна реалізація (CommitteeGrantAuthority):
/// будь-який валідатор (член current_committee) може створити грант,
/// підписавши запит своїм NODE_WALLET_PRIVATE_KEY.
///
/// У майбутньому — OnChainGrantAuthority:
/// перевірка депозиту USDT на PporTreasury.sol через eth_bridge.
pub trait GrantAuthority: Send + Sync {
    /// Перевіряє що `signer` має право створити грант.
    ///
    /// * `signer` — wallet-адреса (0x...)
    /// * `message` — повідомлення яке було підписано
    /// * `signature` — ECDSA підпис (hex, з 0x або без)
    /// * `committee` — поточний комітет валідаторів
    fn can_create_grant(
        &self,
        signer: &str,
        message: &str,
        signature: &str,
        committee: &HashSet<String>,
    ) -> bool;
}

/// Поточна реалізація: будь-який член комітету може створити грант.
pub struct CommitteeGrantAuthority;

impl GrantAuthority for CommitteeGrantAuthority {
    fn can_create_grant(
        &self,
        signer: &str,
        message: &str,
        signature: &str,
        committee: &HashSet<String>,
    ) -> bool {
        // 1. Перевірити що signer у комітеті
        if !committee.contains(signer) {
            eprintln!(
                "[GRANT AUTH] DENIED: signer {} not in committee (size={})",
                signer,
                committee.len()
            );
            return false;
        }

        // 2. Декодувати підпис
        let sig_hex = signature.trim_start_matches("0x");
        let sig_bytes = match hex::decode(sig_hex) {
            Ok(b) if b.len() == 65 => b,
            Ok(b) if b.len() == 64 => {
                // Додати recovery ID = 0 якщо відсутній
                let mut v = vec![0u8; 65];
                v[..64].copy_from_slice(&b);
                v
            }
            _ => {
                eprintln!("[GRANT AUTH] Invalid signature length: {} bytes", sig_hex.len() / 2);
                return false;
            }
        };

        // 3. Хешувати повідомлення (Ethereum personal_sign: "\x19Ethereum Signed Message:\n" + len + msg)
        let prefix = format!(
            "\x19Ethereum Signed Message:\n{}{}",
            message.len(),
            message
        );
        let msg_hash = keccak256(prefix.as_bytes());

        // 4. Відновити публічний ключ
        let secp = Secp256k1::new();
        let recovery_id = ecdsa::RecoveryId::from_i32(sig_bytes[64] as i32).unwrap_or(ecdsa::RecoveryId::from_i32(0).unwrap());
        let recoverable_sig = match ecdsa::RecoverableSignature::from_compact(&sig_bytes[..64], recovery_id) {
            Ok(s) => s,
            Err(e) => {
                eprintln!("[GRANT AUTH] Failed to parse signature: {:?}", e);
                return false;
            }
        };

        let msg = match Message::from_digest_slice(&msg_hash) {
            Ok(m) => m,
            Err(_) => {
                eprintln!("[GRANT AUTH] Failed to create message from hash");
                return false;
            }
        };

        let recovered_pubkey = match secp.recover_ecdsa(&msg, &recoverable_sig) {
            Ok(pk) => pk,
            Err(e) => {
                eprintln!("[GRANT AUTH] Failed to recover public key: {:?}", e);
                return false;
            }
        };

        // 5. Отримати Ethereum-адресу з публічного ключа
        // Публічний ключ у форматі uncompressed: 04 || X (32 bytes) || Y (32 bytes)
        let pubkey_bytes = &recovered_pubkey.serialize_uncompressed()[1..]; // 64 bytes без префікса 04
        let address = &keccak256(pubkey_bytes)[12..]; // останні 20 байт
        let recovered_address = format!("0x{}", hex::encode(address));

        // 6. Порівняти адреси (case-insensitive)
        let is_valid = recovered_address.to_lowercase() == signer.to_lowercase();
        if is_valid {
            eprintln!("[GRANT AUTH] APPROVED: signer={}, recovered={}", signer, recovered_address);
        } else {
            eprintln!(
                "[GRANT AUTH] DENIED: signature mismatch. signer={}, recovered={}",
                signer, recovered_address
            );
        }
        is_valid
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use secp256k1::{PublicKey, SecretKey};
    use std::collections::HashSet;

    /// Генерує тестовий ключ і підписує повідомлення (Ethereum-style).
    fn sign_message(private_key_hex: &str, message: &str) -> (String, String, String) {
        let sk_bytes = hex::decode(private_key_hex).unwrap();
        let sk = SecretKey::from_slice(&sk_bytes).unwrap();
        let secp = Secp256k1::new();
        let pk = PublicKey::from_secret_key(&secp, &sk);

        // Отримати Ethereum-адресу
        let pubkey_bytes = &pk.serialize_uncompressed()[1..];
        let address_bytes = &keccak256(pubkey_bytes)[12..];
        let address = format!("0x{}", hex::encode(address_bytes));

        // Підписати (Ethereum personal_sign)
        let prefix = format!(
            "\x19Ethereum Signed Message:\n{}{}",
            message.len(),
            message
        );
        let msg_hash = keccak256(prefix.as_bytes());
        let msg = Message::from_digest_slice(&msg_hash).unwrap();
        let (recovery_id, sig_bytes) = secp.sign_ecdsa_recoverable(&msg, &sk).serialize_compact();

        let mut full_sig = sig_bytes.to_vec();
        full_sig.push(recovery_id.to_i32() as u8);
        let signature = format!("0x{}", hex::encode(&full_sig));

        let signer = address.clone();
        (address, signature, signer)
    }

    #[test]
    fn test_validator_can_create_grant() {
        let auth = CommitteeGrantAuthority;
        let mut committee = HashSet::new();

        // Генеруємо ключ
        let sk_hex = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2";
        let (address, signature, _signer) = sign_message(sk_hex, "create_grant:test:Test Grant:10000:100");
        committee.insert(address.clone());

        // Перевірка
        assert!(
            auth.can_create_grant(&address, "create_grant:test:Test Grant:10000:100", &signature, &committee),
            "Validator should be able to create grant"
        );
    }

    #[test]
    fn test_non_validator_cannot_create_grant() {
        let auth = CommitteeGrantAuthority;
        let mut committee = HashSet::new();

        // Генеруємо ключ, але НЕ додаємо в комітет
        let sk_hex = "b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3";
        let (address, signature, _signer) = sign_message(sk_hex, "create_grant:test:Test Grant:10000:100");

        // НЕ додаємо в комітет
        // committee.insert(address.clone()); // ← закоментовано

        assert!(
            !auth.can_create_grant(&address, "create_grant:test:Test Grant:10000:100", &signature, &committee),
            "Non-validator should NOT be able to create grant"
        );
    }

    #[test]
    fn test_wrong_message_fails() {
        let auth = CommitteeGrantAuthority;
        let mut committee = HashSet::new();

        let sk_hex = "c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4";
        let (address, signature, _signer) = sign_message(sk_hex, "create_grant:original:Original Title:10000:100");
        committee.insert(address.clone());

        // Перевіряємо з ІНШИМ повідомленням
        assert!(
            !auth.can_create_grant(&address, "create_grant:tampered:Tampered Title:99999:999", &signature, &committee),
            "Wrong message should fail"
        );
    }
}