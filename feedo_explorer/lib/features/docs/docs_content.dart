import 'package:feedo_explorer/l10n/app_localizations.dart';
const String developerDocsMarkdownUk = '''
# Feedo Protocol

Feedo є децентралізованим L1-протоколом та семантичним шаром даних (Web3 Data Grid). Система призначена для зберігання, індексування та маршрутизації даних з використанням криптографічних доказів, алгоритмів консенсусу (PBFT) та технологій векторизації (Embeddings) на базі штучного інтелекту.

Протокол забезпечує інфраструктуру для створення децентралізованих додатків (dApps), які потребують семантичного розуміння контенту, швидкої маршрутизації (Kademlia DHT) та високого рівня доступності даних (Data Availability).

## Технологічний Стек

*   **P2P Core (Низькорівневе ядро):** Rust, `libp2p` (Gossipsub, Kademlia DHT), `sled` (key-value storage).
*   **Консенсус та Стан:** PBFT (Practical Byzantine Fault Tolerance), CRDT (Conflict-free Replicated Data Types).
*   **Semantic API (Прикладний рівень):** Python, `FastAPI`, `SentenceTransformers`, `LanceDB` (Vector DB), `SQLAlchemy` (SQLite).
*   **Серіалізація та IPC:** Protocol Buffers (`protobuf`).
*   **Клієнтський рівень:** SDK (Python, Rust, TS), Flutter (Web/Mobile Explorer).

---

## Архітектурний Дизайн

Архітектура протоколу базується на розділенні функцій мережевої взаємодії та семантичної обробки даних:

1.  **Feedo Core (Rust):** Забезпечує мережевий транспорт. Використовує `libp2p` для встановлення з'єднань між нодами, управління DHT-таблицями маршрутизації та обміну повідомленнями через Gossipsub. Також реалізує логіку консенсусу PBFT для підтвердження транзакцій та зберігає локальний стан у `sled`.
2.  **Feedo API (Python):** Виконує роль семантичного індексатора. Контент, який надходить з P2P-мережі або від клієнтських додатків, векторизується (перетворюється у семантичні ембеддінги) та зберігається у векторній базі даних `LanceDB`. Це забезпечує можливість виконання семантичних запитів.
3.  **Міжпроцесна взаємодія (IPC):** Компоненти на Rust та Python комунікують локально з використанням бінарних `protobuf`-схем (визначених у `feedo.proto`), що мінімізує оверхед на серіалізацію.

---

## Специфікація API (REST/HTTP)

Для розробників, які інтегруються з протоколом Feedo, нода надає локальний/публічний HTTP API (за замовчуванням порт 8000).

### 1. Identity & Authorization (`/identity`)
Відповідає за роботу з децентралізованими ідентифікаторами (DID) та профілями користувачів/нод.

*   `POST /identity/announce` — Реєстрація або оновлення DID-документа у мережі. Вимагає криптографічного підпису.
*   `GET /identity/` — Отримання списку відомих ідентифікаторів у локальній базі.
*   `GET /identity/{public_key}` — Отримання профілю та DID-документа за публічним ключем (Ed25519/Secp256k1).
*   `PUT /identity/update/{public_key}` — Оновлення метаданих профілю.
*   `POST /identity/{public_key}/delegate` — Делегування прав доступу іншому DID.

### 2. Content & Data (`/content`)
Керування базовими блоками контенту (пости, статті, метадані).

*   `POST /content/publish` — Публікація нового запису (транзакції). Дані серіалізуються у Protobuf-повідомлення `FeedoBroadcast`, підписуються автором і відправляються у мемпул P2P-мережі.
*   `GET /content/{hash_id}` — Отримання контенту за його унікальним хешем (SHA-256).
*   `GET /content/status/{hash_id}` — Перевірка статусу транзакції у мемпулі або її стану консенсусу (PBFT).
*   `POST /content/blob` — Завантаження великих бінарних об'єктів (BLOB), які не вміщуються у стандартний розмір повідомлення Gossipsub.
*   `GET /content/blob/{blob_hash}` — Отримання BLOB-даних з розподіленого сховища.

### 3. Semantic Graph & Search (`/semantic`)
Виконання семантичних запитів з використанням векторної бази даних LanceDB.

*   `POST /semantic/query` — Основний ендпоінт для семантичного пошуку. Приймає текстовий запит, генерує ембеддінг та повертає список найближчих векторів (K-Nearest Neighbors) з метаданими контенту.
*   `POST /semantic/validate_uniqueness` — Перевірка унікальності тексту на основі семантичної близькості до існуючих записів у мережі (боротьба зі спамом та дублікатами).
*   `GET /semantic/cluster/{hash_id}` — Отримання кластера семантично схожих об'єктів для конкретного запису.
*   `POST /semantic/feed` — Генерація персоналізованої стрічки на основі масиву векторів інтересів користувача.
*   `GET /semantic/namespace/{namespace_name}` — Вибірка семантичних даних у межах специфічного простору імен (наприклад, конкретного dApp).

### 4. Knowledge Topology (`/graph`)
Навігація по зв'язках між об'єктами (реплаї, цитування, ієрархія).

*   `POST /graph/edge` — Створення спрямованого ребра між двома вузлами (наприклад, коментар до поста).
*   `GET /graph/edges/outbound/{hash_id}` — Отримання вихідних зв'язків (на які об'єкти посилається цей об'єкт).
*   `GET /graph/edges/inbound/{hash_id}` — Отримання вхідних зв'язків (хто посилається на цей об'єкт).
*   `GET /graph/tree/{hash_id}` — Рекурсивне отримання дерева графа (наприклад, дерево коментарів).

### 5. Dynamic CRDT State (`/crdt`)
Робота зі змінними станами без використання централізованих блокувань.

*   `POST /crdt/mutate` — Застосування CRDT-операції (наприклад, `add`, `remove` для `OR-Set` або оновлення реєстру).
*   `GET /crdt/{object_id}` — Отримання поточного консистентного стану CRDT-об'єкта.
*   `POST /crdt/webhook` — Реєстрація вебхука для відстеження змін у конкретних CRDT-об'єктах.

### 6. Node Administration (`/node`)
Моніторинг та налаштування локальної ноди.

*   `GET /node/health` — Перевірка статусу працездатності (Liveness) компонентів Rust та Python.
*   `GET /node/metrics` — Експорт метрик (кількість підключених пірів, розмір мемпулу, затримка PBFT, утилізація пам'яті).
*   `GET /node/peers` — Список активних P2P-з'єднань та їхні адреси (Multiaddr).
*   `POST /node/commercial/api_key` — Генерація API-ключів для обмеження доступу до ноди (для комерційних рішень).

---

## Протокол Комунікації (Protobuf)

Всі дані, що передаються по мережі, строго типізовані. Основні структури визначені у `proto/feedo.proto`.

### Основні структури даних

1.  **`FeedoBroadcast`**: Базовий контейнер для передачі контенту. Містить публічний ключ автора, хеш об'єкта, розмір, підпис та опціональні метадані.
2.  **`PbftMessage`**: Використовується для комунікації між нодами під час консенсусу (Pre-Prepare, Prepare, Commit).
3.  **`CrdtOperation`**: Визначає дельту змін для синхронізації CRDT-стану.

---

## Розгортання та Запуск

Для розгортання повноцінної ноди використовується Docker Compose. Система автоматично піднімає ядро на Rust, бекенд на Python та необхідні бази даних.

### Локальне розгортання (Development)

```bash
# Клонування репозиторію
git clone https://github.com/your-org/feedo.git
cd feedo/feedo

# Запуск ноди
docker-compose up --build
```

Конфігурація середовища здійснюється через файл `.env` у директорії `/feedo`. Основні параметри включають порти для HTTP (8000) та P2P (наприклад, 4001).

### Ініціалізація

Після запуску нода автоматично:
1.  Генерує нову пару ключів ED25519, якщо вона відсутня.
2.  Відкриває порт TCP/UDP (QUIC) для `libp2p`.
3.  Завантажує `Kademlia` bootstrap-адреси.
4.  Створює локальні директорії для `sled` бази та `LanceDB`.

---

## Алгоритми та Механізми

### 1. Маршрутизація (Kademlia DHT)
Протокол використовує розподілену хеш-таблицю для пошуку контенту за його `hash_id` або пошуку нод за їхнім `NodeId`. Це усуває необхідність у центральних індексних серверах.

### 2. Синхронізація (Anti-Entropy)
Для забезпечення узгодженості даних використовується протокол анти-ентропії. Ноди періодично обмінюються деревами Меркла (Merkle Trees) своїх локальних баз. При виявленні розбіжностей ініціюється довантаження відсутніх блоків (DAG Sync).

### 3. Консенсус (PBFT)
Для операцій, що потребують суворого порядку та фіналізації (реєстрація DID, переказ балансів, зміна CRDT-прав), використовується Practical Byzantine Fault Tolerance. Ноди-валідатори проходять фази `Pre-Prepare`, `Prepare` та `Commit`, формуючи криптографічний доказ завершення транзакції.

---

# Структура Проекту Feedo

Проект Feedo складається з низькорівневого мережевого ядра, семантичного API, клієнтських SDK та додаткових інструментів. Дана документація деталізує архітектуру репозиторію та призначення кожного модуля.

## Загальний Огляд Директорій

*   `/feedo/` — Основний код протоколу (Rust P2P Core та Python Semantic API).
*   `/feedo_sdk/` — Бібліотеки (SDK) для розробників, які створюють dApps.
*   `/feedo_explorer/` — Веб-інтерфейс адміністратора ноди та моніторингу мережі.
*   `/legacy_social_archive/` — Архів старого монолітного коду (соціальні функції, чати).

---

## Детальний Опис Компонентів Ноди (`/feedo/`)

Директорія `/feedo` є коренем для розгортання P2P-ноди.

### 1. Feedo Core (`/feedo/feedo-core/`)
Написано на **Rust**. Відповідає за транспортний рівень мережі та криптографію.

*   `src/main.rs`: Точка входу. Ініціалізація `libp2p` Swarm, налаштування транспортів (TCP/QUIC) та обробка системних сигналів.
*   `src/pbft.rs`: Реалізація консенсусу Practical Byzantine Fault Tolerance. Містить логіку станів валідації (Pre-Prepare, Prepare, Commit).
*   `src/did.rs`: Модуль роботи з Decentralized Identifiers (DID). Парсинг, валідація підписів та управління ідентичностями у мережі.
*   `src/crdt.rs`: Рівень управління структурами даних, які не конфліктують (Conflict-free Replicated Data Types).
*   `src/proto.rs`: Автогенерований або кастомний код для взаємодії з Protobuf схемами.

### 2. Feedo API (`/feedo/feedo-api/`)
Написано на **Python** (`FastAPI`). Надає REST API та відповідає за семантичне індексування.

*   `main.py`: Точка входу FastAPI сервера, налаштування CORS та ініціалізація бази даних.
*   `api_v1/`: Директорія з маршрутизаторами (routers).
    *   `content.py`: Ендпоінти для публікації та зчитування об'єктів.
    *   `crdt.py`: Ендпоінти для виконання мутацій CRDT.
    *   `graph.py`: Ендпоінти для побудови та навігації по ребрах графа контенту.
    *   `identity.py`: Ендпоінти управління DID.
    *   `node.py`: Метрики та телеметрія ноди.
    *   `semantic.py`: Запити до векторизованої бази та генерація стрічок.
*   `models.py`: Схеми реляційної бази даних (SQLAlchemy/SQLite).
*   `schemas.py`: Pydantic-моделі для валідації вхідних/вихідних JSON-даних.
*   `vector_brain.py`: Інтеграція з `SentenceTransformers` для створення векторів (Embeddings) та взаємодія з локальною векторною базою `LanceDB`.

### 3. Feedo Parser (`/feedo/feedo_parser/`)
Написано на **Python**. Модуль, що відповідає за бізнес-логіку протоколу та збір зовнішніх даних.

*   `content_sources/`: Парсери для імпорту даних з Web2 (RSS, HackerNews) та Web3 (Nostr).
*   `p2p/`:
    *   `anti_entropy.py`: Логіка синхронізації втрачених даних між нодами (Merkle tree sync).
    *   `crdt_store.py`: Управління локальним станом CRDT на рівні Python.
    *   `reputation.py`: Алгоритми розрахунку репутації та оцінки довіри до пірів.
    *   `replication.py`: Механізми забезпечення Data Availability (DA) та шардування.

### 4. Protobuf Схеми (`/feedo/proto/`)
*   `feedo.proto`: Єдине джерело істини (Single Source of Truth) для структур даних протоколу. Використовується для серіалізації P2P-повідомлень (через Rust) та для IPC (між Rust та Python). Включає схеми `FeedoBroadcast`, `PbftMessage`, `CrdtOperation` та інші.

---

## Життєвий Цикл Даних (Data Flow)

1.  **Генерація Контенту:** dApp формує корисне навантаження та відправляє `POST /content/publish` до `Feedo API`.
2.  **Обробка у Python:** `Feedo API` генерує семантичний вектор контенту (за потреби), зберігає в локальну БД та серіалізує запит у Protobuf-бінарник.
3.  **Транспорт (IPC):** Згенерований бінарник передається локальному процесу `Feedo Core` (Rust) (через сокет або gRPC).
4.  **P2P Трансляція:** Ядро `Feedo Core` отримує завдання та розсилає його всім підключеним пірам через протокол `Gossipsub`.
5.  **Консенсус:** Якщо операція вимагає зміни глобального стану (наприклад, реєстрація імені), ініціюється процес PBFT серед нод-валідаторів.
6.  **Синхронізація:** Ноди, які були офлайн під час Gossip-розсилки, відновлюють дані через механізм Anti-Entropy.

---

## Інфраструктура Розгортання

*   `Dockerfile`: Збірка production-образу, що включає інсталяцію Rust-середовища, компіляцію ядра, встановлення Python-залежностей (`requirements.txt`) та налаштування FastAPI.
*   `docker-compose.yml`: Налаштування локального середовища розробки (DevNet), яке запускає ноду та необхідні бази даних.
*   `start.sh`: Скрипт ініціалізації контейнера, який забезпечує послідовний запуск `feedo-core` (як фонового процесу) та `feedo-api` (через Uvicorn).
''';

const String developerDocsMarkdownEn = '''
# Feedo Protocol

Feedo is a decentralized L1 protocol and a semantic Data Layer (Web3 Data Grid). The system is designed to store, index, and route data using cryptographic proofs, consensus algorithms (PBFT), and AI-based vectorization technologies (Embeddings).

The protocol provides infrastructure for building decentralized applications (dApps) that require semantic content understanding, fast routing (Kademlia DHT), and high Data Availability.

## Technology Stack

*   **P2P Core (Low-level core):** Rust, `libp2p` (Gossipsub, Kademlia DHT), `sled` (key-value storage).
*   **Consensus and State:** PBFT (Practical Byzantine Fault Tolerance), CRDT (Conflict-free Replicated Data Types).
*   **Semantic API (Application layer):** Python, `FastAPI`, `SentenceTransformers`, `LanceDB` (Vector DB), `SQLAlchemy` (SQLite).
*   **Serialization and IPC:** Protocol Buffers (`protobuf`).
*   **Client layer:** SDK (Python, Rust, TS), Flutter (Web/Mobile Explorer).

---

## Architectural Design

The protocol architecture is based on the separation of network interaction and semantic data processing functions:

1.  **Feedo Core (Rust):** Provides network transport. Uses `libp2p` to establish connections between nodes, manage DHT routing tables, and exchange messages via Gossipsub. Also implements PBFT consensus logic for transaction validation and stores local state in `sled`.
2.  **Feedo API (Python):** Acts as a semantic indexer. Content coming from the P2P network or client applications is vectorized (converted into semantic embeddings) and stored in the `LanceDB` vector database. This enables semantic queries.
3.  **Inter-Process Communication (IPC):** Rust and Python components communicate locally using binary `protobuf` schemas (defined in `feedo.proto`), minimizing serialization overhead.

---

## API Specification (REST/HTTP)

For developers integrating with the Feedo protocol, the node provides a local/public HTTP API (port 8000 by default).

### 1. Identity & Authorization (`/identity`)
Responsible for working with Decentralized Identifiers (DID) and user/node profiles.

*   `POST /identity/announce` — Register or update a DID document in the network. Requires cryptographic signature.
*   `GET /identity/` — Get a list of known identifiers in the local database.
*   `GET /identity/{public_key}` — Get a profile and DID document by public key (Ed25519/Secp256k1).
*   `PUT /identity/update/{public_key}` — Update profile metadata.
*   `POST /identity/{public_key}/delegate` — Delegate access rights to another DID.

### 2. Content & Data (`/content`)
Management of basic content blocks (posts, articles, metadata).

*   `POST /content/publish` — Publish a new record (transaction). Data is serialized into a `FeedoBroadcast` Protobuf message, signed by the author, and sent to the P2P network mempool.
*   `GET /content/{hash_id}` — Retrieve content by its unique hash (SHA-256).
*   `GET /content/status/{hash_id}` — Check transaction status in the mempool or its consensus state (PBFT).
*   `POST /content/blob` — Upload large binary objects (BLOB) that don't fit into the standard Gossipsub message size.
*   `GET /content/blob/{blob_hash}` — Retrieve BLOB data from distributed storage.

### 3. Semantic Graph & Search (`/semantic`)
Execute semantic queries using the LanceDB vector database.

*   `POST /semantic/query` — Main endpoint for semantic search. Accepts a text query, generates an embedding, and returns a list of K-Nearest Neighbors with content metadata.
*   `POST /semantic/validate_uniqueness` — Check text uniqueness based on semantic proximity to existing records in the network (spam and duplicate fighting).
*   `GET /semantic/cluster/{hash_id}` — Get a cluster of semantically similar objects for a specific record.
*   `POST /semantic/feed` — Generate a personalized feed based on an array of user interest vectors.
*   `GET /semantic/namespace/{namespace_name}` — Fetch semantic data within a specific namespace (e.g., a specific dApp).

### 4. Knowledge Topology (`/graph`)
Navigation through relationships between objects (replies, citations, hierarchy).

*   `POST /graph/edge` — Create a directed edge between two nodes (e.g., a comment to a post).
*   `GET /graph/edges/outbound/{hash_id}` — Get outbound links (what objects this object refers to).
*   `GET /graph/edges/inbound/{hash_id}` — Get inbound links (who refers to this object).
*   `GET /graph/tree/{hash_id}` — Recursively retrieve a graph tree (e.g., a comment tree).

### 5. Dynamic CRDT State (`/crdt`)
Working with mutable states without centralized locks.

*   `POST /crdt/mutate` — Apply a CRDT operation (e.g., `add`, `remove` for `OR-Set` or register update).
*   `GET /crdt/{object_id}` — Get the current consistent state of a CRDT object.
*   `POST /crdt/webhook` — Register a webhook to track changes in specific CRDT objects.

### 6. Node Administration (`/node`)
Monitoring and configuring the local node.

*   `GET /node/health` — Check Liveness status of Rust and Python components.
*   `GET /node/metrics` — Export metrics (number of connected peers, mempool size, PBFT latency, memory utilization).
*   `GET /node/peers` — List of active P2P connections and their addresses (Multiaddr).
*   `POST /node/commercial/api_key` — Generate API keys to restrict node access (for commercial solutions).

---

## Communication Protocol (Protobuf)

All data transmitted over the network is strictly typed. Main structures are defined in `proto/feedo.proto`.

### Main Data Structures

1.  **`FeedoBroadcast`**: Base container for content transmission. Contains author's public key, object hash, size, signature, and optional metadata.
2.  **`PbftMessage`**: Used for inter-node communication during consensus (Pre-Prepare, Prepare, Commit).
3.  **`CrdtOperation`**: Defines delta changes for CRDT state synchronization.

---

## Deployment and Launch

Docker Compose is used to deploy a fully functional node. The system automatically brings up the Rust core, Python backend, and necessary databases.

### Local Deployment (Development)

```bash
# Clone the repository
git clone https://github.com/your-org/feedo.git
cd feedo/feedo

# Start the node
docker-compose up --build
```

Environment configuration is done via `.env` file in the `/feedo` directory. Main parameters include ports for HTTP (8000) and P2P (e.g., 4001).

### Initialization

After launch, the node automatically:
1.  Generates a new ED25519 key pair if missing.
2.  Opens TCP/UDP (QUIC) port for `libp2p`.
3.  Loads `Kademlia` bootstrap addresses.
4.  Creates local directories for `sled` db and `LanceDB`.

---

## Algorithms and Mechanisms

### 1. Routing (Kademlia DHT)
The protocol uses a distributed hash table to find content by its `hash_id` or find nodes by their `NodeId`. This eliminates the need for central index servers.

### 2. Synchronization (Anti-Entropy)
An anti-entropy protocol is used to ensure data consistency. Nodes periodically exchange Merkle Trees of their local databases. Upon detecting discrepancies, a fetch for missing blocks is initiated (DAG Sync).

### 3. Consensus (PBFT)
Practical Byzantine Fault Tolerance is used for operations requiring strict ordering and finalization (DID registration, balance transfers, CRDT rights changes). Validator nodes go through `Pre-Prepare`, `Prepare`, and `Commit` phases, forming a cryptographic proof of transaction completion.

---

# Feedo Project Structure

The Feedo project consists of a low-level network core, semantic API, client SDKs, and additional tools. This documentation details the repository architecture and the purpose of each module.

## General Directory Overview

*   `/feedo/` — Main protocol code (Rust P2P Core and Python Semantic API).
*   `/feedo_sdk/` — Libraries (SDKs) for developers building dApps.
*   `/feedo_explorer/` — Node admin web interface and network monitoring.
*   `/legacy_social_archive/` — Archive of old monolithic code (social features, chats).

---

## Detailed Node Components Description (`/feedo/`)

The `/feedo` directory is the root for deploying a P2P node.

### 1. Feedo Core (`/feedo/feedo-core/`)
Written in **Rust**. Responsible for the network transport layer and cryptography.

*   `src/main.rs`: Entry point. Initialization of `libp2p` Swarm, transport setup (TCP/QUIC), and OS signal handling.
*   `src/pbft.rs`: Implementation of Practical Byzantine Fault Tolerance consensus. Contains validation state logic (Pre-Prepare, Prepare, Commit).
*   `src/did.rs`: Module for Decentralized Identifiers (DID). Parsing, signature validation, and identity management in the network.
*   `src/crdt.rs`: Management layer for Conflict-free Replicated Data Types.
*   `src/proto.rs`: Auto-generated or custom code for interacting with Protobuf schemas.

### 2. Feedo API (`/feedo/feedo-api/`)
Written in **Python** (`FastAPI`). Provides REST API and handles semantic indexing.

*   `main.py`: FastAPI server entry point, CORS setup, and database initialization.
*   `api_v1/`: Directory with routers.
    *   `content.py`: Endpoints for publishing and reading objects.
    *   `crdt.py`: Endpoints for executing CRDT mutations.
    *   `graph.py`: Endpoints for building and navigating content graph edges.
    *   `identity.py`: DID management endpoints.
    *   `node.py`: Node metrics and telemetry.
    *   `semantic.py`: Queries to the vectorized database and feed generation.
*   `models.py`: Relational database schemas (SQLAlchemy/SQLite).
*   `schemas.py`: Pydantic models for incoming/outgoing JSON data validation.
*   `vector_brain.py`: Integration with `SentenceTransformers` for creating Embeddings and interaction with the local `LanceDB` vector database.

### 3. Feedo Parser (`/feedo/feedo_parser/`)
Written in **Python**. Module responsible for protocol business logic and collecting external data.

*   `content_sources/`: Parsers for importing data from Web2 (RSS, HackerNews) and Web3 (Nostr).
*   `p2p/`:
    *   `anti_entropy.py`: Logic for synchronizing lost data between nodes (Merkle tree sync).
    *   `crdt_store.py`: Local CRDT state management at the Python level.
    *   `reputation.py`: Algorithms for calculating reputation and evaluating peer trust.
    *   `replication.py`: Mechanisms ensuring Data Availability (DA) and sharding.

### 4. Protobuf Schemas (`/feedo/proto/`)
*   `feedo.proto`: Single Source of Truth for protocol data structures. Used for P2P message serialization (via Rust) and IPC (between Rust and Python). Includes `FeedoBroadcast`, `PbftMessage`, `CrdtOperation` schemas and others.

---

## Data Lifecycle (Data Flow)

1.  **Content Generation:** dApp forms payload and sends `POST /content/publish` to `Feedo API`.
2.  **Python Processing:** `Feedo API` generates a semantic vector of the content (if needed), saves to local DB, and serializes the request into a Protobuf binary.
3.  **Transport (IPC):** The generated binary is passed to the local `Feedo Core` (Rust) process (via socket or gRPC).
4.  **P2P Broadcast:** `Feedo Core` receives the task and broadcasts it to all connected peers via the `Gossipsub` protocol.
5.  **Consensus:** If the operation requires global state change (e.g., name registration), a PBFT process is initiated among validator nodes.
6.  **Synchronization:** Nodes that were offline during the Gossip broadcast recover data via the Anti-Entropy mechanism.

---

## Deployment Infrastructure

*   `Dockerfile`: Production image build, including Rust environment installation, core compilation, Python dependencies setup (`requirements.txt`), and FastAPI configuration.
*   `docker-compose.yml`: Local DevNet environment setup that runs the node and necessary databases.
*   `start.sh`: Container initialization script ensuring sequential start of `feedo-core` (as a background process) and `feedo-api` (via Uvicorn).
''';
