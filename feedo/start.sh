#!/bin/bash

# Запускаємо Rust Core у фоні
echo "🚀 Запуск Rust P2P Core..."
./feedo-core &

# Чекаємо 3 секунди, щоб Rust встиг підняти локальний API на порту 8041
sleep 3

if [[ -z "$NODE_TYPE" || "$NODE_TYPE" == "unified" ]]; then
    echo "🕸️ Запуск Nostr Backfill Spider..."
    python backfill_nostr.py --days 180 &
    
    echo "🌉 Запуск Nostr Bridge (Backend)..."
    python feedo_proxy/nostr_bridge.py &
fi

# Запускаємо FastAPI у фоні (тепер він містить і API, і фоновий парсер)
echo "🚀 Запуск FastAPI (API + Monitor)..."
python -m uvicorn main:app --host 0.0.0.0 --port 8040 &

# Команда wait -n змушує контейнер працювати, поки працюють фонові процеси.
# Якщо один з них впаде - контейнер перезапуститься.
wait -n