#!/bin/bash

# Запускаємо Rust Core у фоні
echo "🚀 Запуск Rust P2P Core..."
./feedo-core &

# Чекаємо 3 секунди, щоб Rust встиг підняти локальний API
sleep 3

# Запускаємо Farcaster Hub Ingress у фоні
echo "🚀 Запуск Farcaster Hub Translator (gRPC)..."
./feedo-farcaster &

# Запускаємо FastAPI у фоні
echo "🚀 Запуск FastAPI (API + Monitor)..."
python -m uvicorn main:app --host 0.0.0.0 --port 8040 &

wait -n
