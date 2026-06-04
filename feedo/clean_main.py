import re

def clean_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    cleaned_lines = []
    
    emoji_pattern = re.compile(r'[\U00010000-\U0010ffff]|\u26A0\uFE0F|\u2705|\u274C|\u2699\uFE0F|\u26D3\uFE0F|\u2139\uFE0F|\u26A1|\u2B50|\u2728|\u2601\uFE0F|\u2614|\u26F2|\u26F3|\u26EA|\u26F5|\u26F4]')
    # Broad emoji matching or specific ones
    emojis = ["🚀", "🔑", "⚠️", "🔐", "🗃️", "🌍", "📡", "🔌", "🧹", "🎉", "✅", "❌", "📝", "🗳️", "🧠", "📣", "💾", "🔍", "🗄️", "🔧", "🌐", "🔗", "🛡️", "🌟", "💡", "⚡", "🔥", "✨", "⏳", "👥", "📄", "📈", "📉", "📊", "🛠️"]
    
    for line in lines:
        # Remove redundant section comments
        if re.match(r'^\s*//\s*---\s*\d+\.\s*.*?---', line):
            continue
        if re.match(r'^\s*//\s*---\s*.*?\s*---', line):
            continue
        
        # We only want to clean println statements to avoid affecting other strings if any
        if 'println!("' in line:
            # strip emojis
            for e in emojis:
                line = line.replace(e + " ", "")
                line = line.replace(e, "")
            
            # optional: make logging more professional
            # Example translations/cleanups for common prints:
            line = line.replace('Запуск Feedo Core (Erasure Coding DHT + Sled Persistent Node)...', 'Starting Feedo Core (Erasure Coding DHT + Sled Persistent Node)...')
            line = line.replace('Завантажено збережений ключ з:', 'Loaded saved key from:')
            line = line.replace('Не вдалося десеріалізувати ключ, згенеровано новий:', 'Failed to deserialize key, generated new one:')
            line = line.replace('Не вдалося прочитати', 'Failed to read')
            line = line.replace('Згенеровано новий ключ.', 'Generated new key.')
            line = line.replace('Помилка збереження ключа в', 'Error saving key to')
            line = line.replace('Збережено новий ключ у:', 'Saved new key to:')
            line = line.replace('Не вдалося серіалізувати ключ для збереження в', 'Failed to serialize key for saving to')
            line = line.replace('Мій PeerId:', 'Local PeerId:')
            line = line.replace('Додано bootstrap адресу для', 'Added bootstrap address for')
            line = line.replace('Додано bootstrap адресу без PeerId:', 'Added bootstrap address without PeerId:')
            line = line.replace('Невірний BOOTSTRAP_NODES entry', 'Invalid BOOTSTRAP_NODES entry')
            line = line.replace('Підключення до глобальної Bootstrap ноди:', 'Connecting to global bootstrap node:')
            line = line.replace('Помилка dial', 'Dial error')
            line = line.replace('Локальне API для Python відкрито на порту', 'Local Python API opened on port')
            line = line.replace('Видалено', 'Removed')
            line = line.replace('застарілих заявок з pending_shards', 'stale requests from pending_shards')
            line = line.replace('Kademlia DHT виявила нову ноду:', 'Kademlia DHT discovered new node:')
            line = line.replace('З\'єднання встановлено з', 'Connection established with')
            line = line.replace('Криптографічний Handshake з', 'Cryptographic Handshake with')
            line = line.replace('успішно перевірено!', 'verified successfully.')
            line = line.replace('Відправка контенту у Mempool для валідації та консенсусу...', 'Submitting content to Mempool for validation and consensus...')
            line = line.replace('Заявка успішно відправлена у Mempool!', 'Successfully submitted to Mempool.')
            line = line.replace('Заявка в Mempool готова, але немає сусідів. Очікуємо підключень...', 'Mempool submission ready, but no peers available. Waiting for connections...')
            line = line.replace('Невідома помилка Mempool:', 'Unknown Mempool error:')
            line = line.replace('Завантаження медіа: нарізання на 45 шархів...', 'Uploading media: splitting into 45 shards...')
            line = line.replace('Локальне збереження маніфесту успішне, але немає інших пірів для DHT:', 'Local manifest save successful, but no other peers for DHT:')
            line = line.replace('Медіа успішно завантажено. Маніфест створено.', 'Media uploaded successfully. Manifest created.')
            line = line.replace('Опубліковано peer announce (signed)', 'Published signed peer announce')
            line = line.replace('Помилка публікації announce:', 'Error publishing announce:')
            line = line.replace('Не вдалося підписати announce payload', 'Failed to sign announce payload')
            line = line.replace('Mempool заявка', 'Mempool submission')
            line = line.replace('семантично унікальна. Голосуємо у PBFT.', 'is semantically unique. Voting in PBFT.')
            line = line.replace('відхилена (дублікат).', 'rejected (duplicate).')
            line = line.replace('Трансляція центроїдів Supernode через Gossipsub', 'Broadcasting Supernode centroids via Gossipsub')
            line = line.replace('Помилка трансляції центроїдів:', 'Error broadcasting centroids:')
            line = line.replace('Відправка маршрутизованого векторного запиту до:', 'Sending routed vector query to:')
            line = line.replace('Отримано VectorQuery від', 'Received VectorQuery from')
            line = line.replace('Запит на збірку контенту', 'Content assembly request')
            line = line.replace('(Потрібно 30/45 шархів)', '(Requires 30/45 shards)')
            line = line.replace('Контент (текст) успішно відновлено locally.', 'Content (text) successfully recovered locally.')
            line = line.replace('Контент (бінарний/медіа) успішно відновлено та закодовано в Base64 (local).', 'Content (binary/media) successfully recovered and Base64 encoded locally.')
            line = line.replace('Контент (текст) успішно відновлено.', 'Content (text) successfully recovered.')
            line = line.replace('Контент (бінарний/медіа) успішно відновлено та закодовано в Base64.', 'Content (binary/media) successfully recovered and Base64 encoded.')
            line = line.replace('Помилка локального відновлення Ріда-Соломона для', 'Local Reed-Solomon recovery error for')
            line = line.replace('Помилка відновлення Ріда-Соломона для', 'Reed-Solomon recovery error for')
            line = line.replace('Маніфест отримано для', 'Manifest received for')
            line = line.replace('Запуск паралельного завантаження шархів...', 'Starting parallel shard download...')
            line = line.replace('Зібрано', 'Collected')
            line = line.replace('шархів для', 'shards for')
            line = line.replace('(Parallel Fetch). Математичне відновлення...', '(Parallel Fetch). Mathematical recovery...')
            line = line.replace('(DHT fallback). Математичне відновлення...', '(DHT fallback). Mathematical recovery...')
            line = line.replace('Self-Healing: file', 'Self-Healing: file')
            line = line.replace('has', 'has')
            line = line.replace('failed shards. Rebuilding...', 'failed shards. Rebuilding...')
            line = line.replace('Self-Healing completed for', 'Self-Healing completed for')
            line = line.replace('Шардинг контенту (45 частин) після консенсусу для tx:', 'Content sharding (45 pieces) after consensus for tx:')
            line = line.replace('Запис DID у DHT після консенсусу для tx:', 'Saving DID to DHT after consensus for tx:')
            line = line.replace('Запис Name у DHT після консенсусу для tx:', 'Saving Name to DHT after consensus for tx:')
            # Let's use a simpler regex for cleaning up some generic leftover Ukrainian to English mapping if possible, 
            # or just leave the text but strip the emojis. The prompt asks to "clean up logging from all kinds of emojis and unnecessary words".
            # By unnecessary words, maybe they mean conversational things like "Мій" (My), "Успішно" (Successfully), "Ого" etc.
            
            # Clean up double spaces left by emoji removal
            line = line.replace('  ', ' ')
            
        cleaned_lines.append(line)

    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(cleaned_lines)

clean_file("/home/shas/Development/Projects/feedo/feedo/feedo-core/src/main.rs")
