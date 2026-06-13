import re

file_path = "/home/shas/Development/Projects/feedo/feedo/feedo-core/src/main.rs"
with open(file_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

translation_map = {
    '🚀 Запуск Feedo Core (Erasure Coding DHT + Sled Persistent Node)...': '🚀 Starting Feedo Core (Erasure Coding DHT + Sled Persistent Node)...',
    'Завантажено збережений ключ з': 'Loaded saved key from',
    'Не вдалося десеріалізувати ключ, згенеровано новий': 'Failed to deserialize key, generated new one',
    'Не вдалося прочитати': 'Failed to read',
    'Згенеровано новий ключ.': 'Generated new key.',
    'Помилка збереження ключа в': 'Error saving key to',
    'Збережено новий ключ у': 'Saved new key to',
    'Не вдалося серіалізувати ключ для збереження в': 'Failed to serialize key for saving to',
    'Мій PeerId': 'My PeerId',
    'Додано bootstrap адресу': 'Added bootstrap address',
    'для': 'for',
    'без PeerId': 'without PeerId',
    'Невірний BOOTSTRAP_NODES entry': 'Invalid BOOTSTRAP_NODES entry',
    'Підключення до глобальної Bootstrap ноди': 'Connecting to global Bootstrap node',
    'Додано зовнішню адресу (EXTERNAL_IP)': 'Added external address (EXTERNAL_IP)',
    'Неправильний формат EXTERNAL_IP': 'Invalid EXTERNAL_IP format',
    'Помилка dial': 'Dial error',
    '🔌 Локальне API для Python відкрито на порту 8041': '🔌 Local Python API opened on port 8041',
    'Шардинг контенту (45 частин) після консенсусу для tx': 'Content sharding (45 pieces) after consensus for tx',
    'Локальне збереження маніфесту успішне, але немає інших пірів для DHT': 'Local manifest save successful, but no other peers for DHT',
    'Запис DID у DHT після консенсусу для tx': 'Recording DID in DHT after consensus for tx',
    'Запис Name у DHT після консенсусу для tx': 'Recording Name in DHT after consensus for tx',
    'Запис Schema у DHT після консенсусу для tx': 'Recording Schema in DHT after consensus for tx',
    '🔍 Надсилаємо PoStChallenge для': '🔍 Sending PoStChallenge for',
    'до': 'to',
    'Запит на збірку контенту': 'Content assembly request',
    '(Потрібно 30/45 шархів)': '(Requires 30/45 shards)',
    'Контент (текст) успішно відновлено locally.': 'Content (text) successfully recovered locally.',
    'Контент (бінарний/медіа) успішно відновлено та закодовано в Base64 (local).': 'Content (binary/media) successfully recovered and encoded to Base64 (local).',
    'Контент (текст) успішно відновлено.': 'Content (text) successfully recovered.',
    'Контент (бінарний/медіа) успішно відновлено та закодовано в Base64.': 'Content (binary/media) successfully recovered and encoded to Base64.',
    'Помилка локального відновлення Ріда-Соломона для': 'Local Reed-Solomon recovery error for',
    'Помилка відновлення Ріда-Соломона для': 'Reed-Solomon recovery error for',
    'GC: Видалено': 'GC: Removed',
    'застарілих заявок з pending_shards': 'stale requests from pending_shards',
    'Зібрано': 'Collected',
    'шархів для': 'shards for',
    'шардів': 'shards',
    '(DHT fallback). Математичне відновлення...': '(DHT fallback). Mathematical recovery...',
    '(Parallel Fetch). Математичне відновлення...': '(Parallel Fetch). Mathematical recovery...',
    'Kademlia DHT виявила нову ноду': 'Kademlia DHT discovered a new node',
    'З\'єднання встановлено з': 'Connection established with',
    'Отримано VectorQuery від': 'Received VectorQuery from',
    '🔍 Отримано PoStChallenge для фрагменту': '🔍 Received PoStChallenge for chunk',
    'від': 'from',
    'Відправлено PoStResponse для': 'Sent PoStResponse for',
    'Фрагмент': 'Chunk',
    'не знайдено для PoStChallenge': 'not found for PoStChallenge',
    'Криптографічний Handshake з': 'Cryptographic Handshake with',
    'успішно перевірено!': 'successfully verified!',
    'Отримано PoStResponse від': 'Received PoStResponse from',
    'Хеш': 'Hash',
    'Неможливо відновити файл': 'Unable to recover file',
    'Зібрано лише': 'Collected only',
    'Маніфест отримано для': 'Manifest received for',
    'Запуск паралельного завантаження шархів...': 'Starting parallel shard download...',
    '🧠 Отримано відповідь на VectorQuery': '🧠 Received response to VectorQuery',
    'Не вдалося отримати маніфест для': 'Failed to fetch manifest for',
    'mDNS знайшов сусіда': 'mDNS found neighbor',
    'на': 'on'
}

def translate_line(line):
    if "println!(" not in line and "eprintln!(" not in line and "println" not in line:
        return line
    for ukr, eng in translation_map.items():
        line = line.replace(ukr, eng)
    # Additional ad-hoc translations based on regex:
    line = re.sub(r'Неможливо відновити файл (.*?)\. Зібрано лише (\d+)/(\d+) шардів\.', r'Unable to recover file \1. Collected only \2/\3 shards.', line)
    return line

with open(file_path, "w", encoding="utf-8") as f:
    for line in lines:
        f.write(translate_line(line))

print("Translation script executed.")
