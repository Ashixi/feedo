#!/bin/bash

# Запускаємо Rust Core у фоні
echo "🚀 Запуск Rust P2P Core..."
./feedo-core &

# Чекаємо 3 секунди, щоб Rust встиг підняти локальний API на порту 8041
sleep 3

# Запускаємо FastAPI у фоні (тепер він містить і API, і фоновий парсер)
echo "🚀 Запуск FastAPI (API + Monitor)..."
python -m uvicorn main:app --host 0.0.0.0 --port 8040 &

# Команда wait -n змушує контейнер працювати, поки працюють фонові процеси.
# Якщо один з них впаде - контейнер перезапуститься.
wait -n