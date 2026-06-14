# Структура Проекту Feedo

Проект Feedo складається з низькорівневого мережевого ядра, семантичного API, клієнтських SDK, смарт-контрактів та додаткових інструментів. Дана документація деталізує архітектуру репозиторію та призначення кожного модуля.

## Загальний Огляд Директорій

*   `/feedo/` — Основний код протоколу (Rust P2P Core, Python Semantic API, Proxy, Smart Contracts).
*   `/feedo_sdk/` — Бібліотеки (SDK) для розробників, які створюють dApps.
*   `/feedo_explorer/` — Веб-інтерфейс адміністратора ноди та моніторингу мережі.
*   `/legacy_social_archive/` — Архів старого монолітного коду (соціальні функції, чати).

---

## Детальний Опис Компонентів Ноди (`/feedo/`)

Директорія `/feedo` є коренем для розгортання гібридної P2P-ноди (Feedo Protocol + Nostr).

### 1. Feedo Core (`/feedo/feedo-core/`)
Написано на **Rust**. Відповідає за транспортний рівень мережі, P2P-зв'язок (Gossipsub, Kademlia), криптографію та Nostr-релей.

*   `src/main.rs`: Точка входу. Ініціалізація `libp2p` Swarm, налаштування транспортів, обробка системних сигналів та глобального стейту.
*   `src/bin/feedo_nostr.rs`: Гібридний Nostr WebSocket-релей на базі `axum`. Приймає стандартні з'єднання NIP-01, NIP-11, підтримує Live Subscriptions та перенаправляє запити NIP-50 до векторної бази.
*   `src/nostr_db.rs`: Вбудована SQLite база даних для зберігання подій Nostr. Реалізує логіку заміни (NIP-16, NIP-33), видалення (NIP-09) та строку дії (NIP-40).
*   `src/pbft.rs`: Реалізація консенсусу Practical Byzantine Fault Tolerance. Містить логіку станів валідації (Pre-Prepare, Prepare, Commit).
*   `src/did.rs`: Модуль роботи з Decentralized Identifiers (DID). Парсинг, валідація підписів Schnorr/Ed25519 та управління ідентичностями у мережі.
*   `src/crdt.rs`: Рівень управління структурами даних, які не конфліктують (Conflict-free Replicated Data Types).
*   `src/proto.rs`: Обгортка для взаємодії з Protobuf схемами.

### 2. Feedo API (`/feedo/feedo-api/`)
Написано на **Python** (`FastAPI`). Надає REST API, відповідає за AI-пошук (LanceDB + SentenceTransformers) та інтеграцію токеноміки.

*   `main.py`: Точка входу FastAPI сервера, налаштування CORS та ініціалізація векторної бази даних (LanceDB).
*   `api_v1/`: Директорія з маршрутизаторами (routers).
    *   `content.py`: Ендпоінти для публікації та зчитування об'єктів. Виконує Zero Trust валідацію підписів та проксіює дані у Rust-ядро через бінарний Protobuf.
    *   `crdt.py`: Ендпоінти для виконання мутацій CRDT (AwOrSet тощо).
    *   `graph.py`: Ендпоінти для побудови та навігації по ребрах графа контенту.
    *   `identity.py`: Ендпоінти управління DID та ідентичностями.
    *   `node.py`: Метрики та телеметрія ноди (CPU, RAM, P2P peers).
    *   `semantic.py`: Запити до векторизованої бази (LanceDB), генерація стрічок.
*   `models.py`: Схеми реляційної бази даних (SQLAlchemy + PostgreSQL / asyncpg).
*   `schemas.py`: Pydantic-моделі для валідації вхідних/вихідних JSON-даних.
*   `vector_brain.py`: Інтеграція з локальною векторною базою (LanceDB) та побудова NLP-векторів (SentenceTransformers).

### 3. Feedo Parser & Protocol Logic (`/feedo/feedo_parser/`)
Написано на **Python**. Модуль, що відповідає за бізнес-логіку протоколу, криптографію та репутацію.

*   `crypto_utils.py`: Реалізація Zero Trust безпеки (Ed25519 через PyNaCl), генерація і перевірка цифрових підписів для ідентичності та публікацій.
*   `p2p/`:
    *   `anti_entropy.py`: Логіка синхронізації втрачених даних між нодами (Merkle tree sync).
    *   `crdt_store.py`: Управління локальним станом CRDT на рівні Python.
    *   `reputation.py`: Алгоритми розрахунку репутації та оцінки довіри до пірів.
    *   `discovery.py`: Bootstrap та пошук нових пірів.
    *   `key_manager.py`: Управління криптографічними ключами.
    *   `upload_manager.py`: Логіка Proof-of-Storage та розрахунків з Data Availability шаром.

### 4. Proxy та Бріджі (`/feedo/feedo_proxy/`)
Написано на **Python**. Фонова синхронізація з іншими екосистемами.

*   `nostr_bridge.py`: Фоновий демон-краулер. Підключається до глобальних релеїв (Damus, Nos.lol тощо), завантажує стрічки та відправляє їх на локальний порт `feedo_nostr` для "прогріву" бази даних.

### 5. Smart Contracts (`/feedo/contracts/`)
Написано на **Solidity**. Смарт-контракти токеноміки в мережі Polygon.

*   `FeedoPayment.sol`: Контракт для мікротранзакцій, Pay-per-query, винагород валидаторів та Proof-of-Storage виплат. Інтегрується через `eth_bridge.rs` у Rust-ядрі.

### 6. Protobuf Схеми (`/feedo/proto/`)
*   `feedo.proto`: Єдине джерело істини (Single Source of Truth) для структур даних протоколу. Використовується для серіалізації P2P-повідомлень (через Rust) та для строго типізованого IPC (між Rust та Python). Python API безпосередньо компілює та використовує `feedo_pb2.py` для відправки `PublishRequest` у ядро.

---

## Життєвий Цикл Даних (Data Flow)

1.  **Генерація Контенту:** Клієнт підписує пост власним Ed25519 ключем і відправляє: 
    *   Через REST: `POST /content/publish` до `Feedo API`.
2.  **Zero Trust Валідація:** Python API (`crypto_utils.py`) перевіряє `signature` відносно `hash_id`. Якщо підпис валідний, дані упаковуються в бінарний Protobuf.
3.  **Зберігання та Індексація:** `Feedo API` зберігає реляційні метадані у `PostgreSQL` та передає текст для генерації AI-векторів у `LanceDB`.
4.  **Транспорт (IPC):** Згенерований бінарник (Protobuf) передається між процесами від Python API до Rust-ядра (`/local/publish`).
5.  **P2P Трансляція та Мемпул:** Ядро `Feedo Core` перевіряє Protobuf-схему та розміщує пост у `mempool` для PBFT-консенсусу, після чого розсилає його всім підключеним Feedo-нодам через протокол `Gossipsub`.
6.  **Зберігання (DHT):** `Feedo Core` використовує Erasure Coding (Reed-Solomon) та зберігає шарди даних у розподіленій `Kademlia` DHT на базі локального `sled` сховища.

---

## Інфраструктура Розгортання та Тестування

*   `Dockerfile`: Образ для підняття гібридної ноди (компіляція Rust-ядра `feedo-core`, генерація Protobuf `feedo_pb2`, встановлення Python API).
*   `docker-compose.yml` / `docker-compose.test.yml`: Налаштування середовища (DevNet / Prod), яке піднімає `PostgreSQL` базу даних та P2P ноду (контейнер `feedo_node`).
*   `test_local_system.py`: Скрипт інтеграційного тестування. Генерує Ed25519 ключі "на льоту" (через PyNaCl) для імітації Zero Trust взаємодії з усіма ендпоінтами без запуску важких ML-моделей.