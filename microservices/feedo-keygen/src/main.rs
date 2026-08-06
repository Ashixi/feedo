use ed25519_dalek::SigningKey;
use rand::rngs::OsRng;
use serde::Serialize;
use sha3::{Digest, Keccak256};

#[derive(Serialize)]
struct NodeKeys {
    private_key: String,
    public_key: String,
    address: String,
    did: String,
}

fn main() {
    // Generate a random Ed25519 signing key
    let mut csprng = OsRng;
    let signing_key = SigningKey::generate(&mut csprng);
    let verifying_key = signing_key.verifying_key();

    let private_key_hex = hex::encode(signing_key.to_bytes());
    let public_key_hex = hex::encode(verifying_key.to_bytes());

    // Derive Ethereum-compatible address from public key via Keccak256
    let mut hasher = Keccak256::new();
    hasher.update(verifying_key.to_bytes());
    let hash = hasher.finalize();
    // Take last 20 bytes (Ethereum address convention)
    let address = format!("0x{}", hex::encode(&hash[12..]));

    let did = format!("did:feedo:{}", &address[2..]); // strip "0x"

    let keys = NodeKeys {
        private_key: private_key_hex,
        public_key: public_key_hex,
        address,
        did,
    };

    println!("{}", serde_json::to_string_pretty(&keys).unwrap());
}
