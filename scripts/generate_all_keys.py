"""
Feedo — Key Generator for .env file

Usage:
  python scripts/generate_all_keys.py

Prints ready-to-paste lines for your .env file.
"""

import secrets
import string


def generate_ed25519_hex() -> str:
    """Generate a 64-character hex Ed25519 private key (32 bytes = 64 hex chars)."""
    return secrets.token_bytes(32).hex()


def generate_evm_wallet():
    """Generate an Ethereum wallet (private key + address)."""
    from eth_account import Account
    priv_key_bytes = secrets.token_bytes(32)
    priv_key_hex = priv_key_bytes.hex()
    account = Account.from_key("0x" + priv_key_hex)
    return priv_key_hex, account.address


def generate_password(length: int = 24) -> str:
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def main():
    sep = "=" * 60

    print(sep)
    print("   F E E D O   --   Key Generator")
    print(sep)
    print()
    print("[*] Generating keys...")
    print()

    # 1. Consensus Node Ed25519 key
    consensus_key = generate_ed25519_hex()

    # 2. Storage Node Ed25519 key
    storage_key = generate_ed25519_hex()

    # 3. EVM Wallet
    try:
        wallet_priv, wallet_addr = generate_evm_wallet()
    except ImportError:
        print("[!] eth_account not installed. Run: pip install eth-account")
        print("    Skipping EVM wallet generation.")
        wallet_priv = ""
        wallet_addr = "0x0000000000000000000000000000000000000000"

    # 4. PostgreSQL password
    pg_password = generate_password()

    print(sep)
    print("   Copy these lines into your .env file:")
    print(sep)
    print()

    print("# --- Consensus Node (feedo-p2p) ---")
    print(f"NODE_PRIVATE_KEY={consensus_key}")
    print()

    print("# --- Storage Node (feedo-backend) ---")
    print(f"STORAGE_PRIVATE_KEY={storage_key}")
    print()

    print("# --- EVM Wallet (Validator Identity) ---")
    print(f"NODE_WALLET_PRIVATE_KEY={wallet_priv}")
    print(f"NODE_WALLET_ADDRESS={wallet_addr}")
    print()

    print("# --- PostgreSQL ---")
    print(f"POSTGRES_PASSWORD={pg_password}")
    print()

    print(sep)
    print("[!] IMPORTANT:")
    print("1. Save these keys in a safe place!")
    print("2. NEVER share your private keys with anyone.")
    print("3. NODE_WALLET_ADDRESS is your identity in the validator committee.")
    print("4. Consensus and Storage use DIFFERENT Ed25519 keys.")
    print(sep)


if __name__ == "__main__":
    main()