import secrets
import sys

try:
    from ecdsa import SECP256k1, SigningKey
    HAS_ECDSA = True
except ImportError:
    HAS_ECDSA = False

def generate_keys():
    print("=== Feedo Node Key Generator ===")
    print("Generating keys for your node...\n")
    
    # 1. RSS Secret (just a random string to secure RSS feeds)
    rss_secret = secrets.token_hex(16)
    
    # 2. Nostr Keypair
    priv_key_bytes = secrets.token_bytes(32)
    priv_key_hex = priv_key_bytes.hex()
    
    if HAS_ECDSA:
        sk = SigningKey.from_string(priv_key_bytes, curve=SECP256k1)
        vk = sk.get_verifying_key()
        # Nostr uses x-only public keys (first 32 bytes)
        pub_key_hex = vk.to_string()[:32].hex()
    else:
        pub_key_hex = "<Run 'pip install ecdsa' to generate public key automatically>"
        
    # 3. Ingest API Key
    ingest_api_key = secrets.token_urlsafe(32)
    
    # 4. Postgres Password
    postgres_password = secrets.token_urlsafe(24)

    print("Copy these values into your .env file:\n")
    print(f"POSTGRES_PASSWORD={postgres_password}")
    print(f"INGEST_API_KEY={ingest_api_key}")
    print(f"RSS_NODE_SECRET={rss_secret}")
    print(f"NODE_WALLET_PRIVATE_KEY={priv_key_hex}")
    print(f"NODE_WALLET_ADDRESS={pub_key_hex}")
    print("\n================================")
    
    if not HAS_ECDSA:
        print("\nWarning: the `ecdsa` library is not installed.")
        print("To allow the script to calculate NODE_WALLET_ADDRESS automatically, run: pip install ecdsa")

if __name__ == "__main__":
    generate_keys()
