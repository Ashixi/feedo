#!/bin/bash

# Запускаємо Rust Core у фоні
echo "🚀 Запуск Rust P2P Core..."
./feedo-core &

# Чекаємо 3 секунди, щоб Rust встиг підняти локальний API
sleep 3

# Запускаємо Nostr WebSocket Relay у фоні
echo "🚀 Запуск Nostr Relay (NIP-01, 11, 50)..."
./feedo-nostr &

# Запускаємо FastAPI у фоні
echo "🚀 Запуск FastAPI (API + Monitor)..."
python -m uvicorn main:app --host 0.0.0.0 --port 8040 &

wait -n
