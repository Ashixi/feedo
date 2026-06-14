#!/usr/bin/env python3
import secrets

def main():
    print("=======================================")
    print("🚀 Feedo Node Keys Generator 🚀")
    print("=======================================\n")
    
    # Генеруємо 32-байтний seed для Ed25519 (64 hex-символи)
    wallet_key = secrets.token_hex(32)
    
    # Генеруємо випадковий пароль для ноди (безпечний для URL)
    node_secret = secrets.token_urlsafe(32)
    
    print("Скопіюйте ці рядки та вставте їх у ваш файл '.env':\n")
    print(f"NODE_WALLET_PRIVATE_KEY={wallet_key}")
    print(f"RSS_NODE_SECRET={node_secret}")
    
    print("\n⚠️ ВАЖЛИВО: Збережіть ці ключі в надійному місці!")
    print("Якщо ви втратите NODE_WALLET_PRIVATE_KEY, ви втратите доступ до своєї ідентичності та токенів.\n")

if __name__ == "__main__":
    main()
