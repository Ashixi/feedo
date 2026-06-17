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

# Запускаємо Continuous Backfill Spider у фоні (чекаємо 10 сек, щоб FastAPI ініціалізував БД)
echo "🕸️ Запуск Nostr Backfill Spider..."
sleep 10
python backfill_nostr.py --days 180 &

wait -n
