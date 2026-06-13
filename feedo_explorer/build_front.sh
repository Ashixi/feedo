#!/bin/bash
set -e

echo "🚀 Білд Flutter через Docker..."

# Збираємо тимчасовий образ з Flutter (викличе кешовані шари для SDK, але перезбере код)
docker build --build-arg CACHEBUST=$(date +%s) -t feedo-web-builder -f Dockerfile .

echo "📦 Експортуємо скомпільовану папку web на хост..."

# Створюємо тимчасовий контейнер
docker create --name temp-builder feedo-web-builder

# Видаляємо стару папку build/web, якщо вона є
rm -rf build/web

# Копіюємо папку build/web з контейнера на хост
docker cp temp-builder:/app/build/web ./build/web

# Видаляємо тимчасовий контейнер
docker rm temp-builder

echo "✅ Готово! Фронтенд успішно зібрано і він знаходиться у папці feedo_explorer/build/web"
