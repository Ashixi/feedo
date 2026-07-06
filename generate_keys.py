from eth_account import Account
import secrets

def generate_evm_wallet():
    # Генеруємо 32 байти безпечного випадкового числа
    priv_key_bytes = secrets.token_bytes(32)
    priv_key_hex = priv_key_bytes.hex()
    
    # Отримуємо акаунт (та публічну адресу) з цього приватного ключа
    account = Account.from_key("0x" + priv_key_hex)
    
    print("="*45)
    print("   Feedo Node Wallet Generator")
    print("="*45)
    print("\n✅ Успішно згенеровано новий гаманець!\n")
    
    print("Скопіюй ці рядки у свій .env файл:\n")
    print(f"NODE_WALLET_PRIVATE_KEY={priv_key_hex}")
    print(f"NODE_WALLET_ADDRESS={account.address}\n")
    
    print("="*45)
    print("🚨 ВАЖЛИВО:")
    print("1. НІКОЛИ не показуй нікому свій PRIVATE_KEY.")
    print("2. Саме ADDRESS (починається з 0x) ти маєш вставляти як Committee Address під час деплою.")
    print("="*45)

if __name__ == "__main__":
    generate_evm_wallet()
