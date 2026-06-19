#!/bin/bash

# Запускаємо Rust Core у фоні
echo "🚀 Запуск Rust P2P Core..."
./feedo-core &

# Чекаємо 3 секунди, щоб Rust встиг підняти локальний API
sleep 3

if [[ -z "$NODE_TYPE" || "$NODE_TYPE" == "unified" || "$NODE_TYPE" == "nostr" ]]; then
    # Запускаємо Nostr WebSocket Relay у фоні
    echo "🚀 Запуск Nostr Relay (NIP-01, 11, 50)..."
    ./feedo-nostr &
fi

# Запускаємо FastAPI у фоні
echo "🚀 Запуск FastAPI (API + Monitor)..."
python -m uvicorn main:app --host 0.0.0.0 --port 8040 &

# Запускаємо Continuous Backfill Spiders у фоні (чекаємо 10 сек, щоб FastAPI ініціалізував БД)
sleep 10

if [[ -z "$NODE_TYPE" || "$NODE_TYPE" == "unified" || "$NODE_TYPE" == "nostr" ]]; then
    echo "🕸️ Запуск Nostr Backfill Spider..."
    python backfill_nostr.py --days 180 &
fi


wait -n
