#!/usr/bin/env python3
import secrets

def main():
    print("=======================================")
    print("🚀 Feedo Node Keys Generator 🚀")
    print("=======================================\n")
    
    # Generate a 32-byte seed for Ed25519 (64 hex characters)
    wallet_key = secrets.token_hex(32)
    
    # Generate a random password for the node (URL-safe)
    node_secret = secrets.token_urlsafe(32)
    
    print("Copy these lines and paste them into your '.env' file:\n")
    print(f"NODE_WALLET_PRIVATE_KEY={wallet_key}")
    print(f"RSS_NODE_SECRET={node_secret}")
    
    print("\n⚠️ IMPORTANT: Keep these keys in a safe place!")
    print("If you lose your NODE_WALLET_PRIVATE_KEY, you will lose access to your identity and tokens.\n")

if __name__ == "__main__":
    main()
