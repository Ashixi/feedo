# Feedo Protocol

🌍 [English](#feedo-protocol-en) | 🇺🇦 [Українська](#feedo-protocol-uk)

---

<a name="feedo-protocol-en"></a>
# Feedo Protocol (EN)

Feedo is the Unified Semantic Layer for the decentralized internet (let's boldly call it Web4, haha). The core vision is for Feedo to serve as a foundational protocol and infrastructure layer where developers can build the decentralized applications (dApps) of the future. It provides a censorship-resistant, sharded P2P storage system with native AI-powered semantic search.

To overcome the "empty network" problem and accelerate Go-To-Market, Feedo acts as a universal "global brain" that initially ingests data from fragmented networks—like Nostr and Farcaster. This strategy populates the global semantic graph with life from day one, allowing users to discover existing content by its **meaning** rather than exact keywords, and creating a fertile ground for new ecosystem projects.

## Tech Stack

*   **P2P Core (Low-level core):** Rust, `libp2p` (Gossipsub, Kademlia DHT), `sled` (key-value storage).
*   **Consensus & State:** PBFT (Practical Byzantine Fault Tolerance), CRDT (Conflict-free Replicated Data Types).
*   **Semantic API (Application layer):** Python, `FastAPI`, `SentenceTransformers`, `LanceDB` (Vector DB), `SQLAlchemy` (SQLite).
*   **Smart Contracts (Tokenomics):** Solidity (EVM) for PBFT validator rewards and micro-transactions.
*   **Serialization & IPC:** Protocol Buffers (`protobuf`), gRPC.
*   **Client layer:** SDK (Python, Rust, TS), Flutter (Web/Mobile Explorer).

---

## Architectural Design

The architecture of the protocol is based on the separation of network interaction and semantic data processing functions:

1.  **Feedo Core (Rust):** Provides network transport. Uses `libp2p` to establish connections between nodes, manage DHT routing tables, and exchange messages via Gossipsub. It also implements the PBFT consensus logic to confirm transactions and stores local state in `sled`.
2.  **Feedo API (Python):** Acts as a semantic indexer. Content arriving from the P2P network or client applications is vectorized (converted into semantic embeddings) and stored in the `LanceDB` vector database. This enables semantic queries.
3.  **Protocol Bridges (Ingress Nodes):** Feedo can act as a "Hybrid Node" for existing decentralized networks. We currently natively support bridging **Nostr** (WebSocket relay) and **Farcaster** (gRPC Hub). Messages from these networks are automatically translated, semantically indexed, and stored in the global Feedo DHT.
4.  **Inter-process Communication (IPC):** Rust and Python components communicate locally using binary `protobuf` schemas (defined in `feedo.proto`), minimizing serialization overhead.

---

## API Specification (REST/HTTP)

For developers integrating with the Feedo protocol, a node provides a local/public HTTP API (default port 8000).

### 1. Identity & Authorization (`/identity`)
Responsible for handling decentralized identifiers (DID) and user/node profiles.

*   `POST /identity/announce` — Register or update a DID document on the network. Requires a cryptographic signature.
*   `GET /identity/` — Retrieve the list of known identifiers in the local database.
*   `GET /identity/{public_key}` — Retrieve profile and DID document by public key (Ed25519/Secp256k1).
*   `PUT /identity/update/{public_key}` — Update profile metadata.
*   `POST /identity/{public_key}/delegate` — Delegate access rights to another DID.

### 2. Content & Data (`/content`)
Manage basic content blocks (posts, articles, metadata).

*   `POST /content/publish` — Publish a new entry (transaction). Data is serialized into a `FeedoBroadcast` Protobuf message, signed by the author, and sent to the P2P network mempool.
*   `GET /content/{hash_id}` — Retrieve content by its unique hash (SHA-256).
*   `GET /content/status/{hash_id}` — Check transaction status in the mempool or its consensus state (PBFT).
*   `POST /content/blob` — Upload large binary objects (BLOBs) that do not fit into the standard Gossipsub message size.
*   `GET /content/blob/{blob_hash}` — Retrieve BLOB data from the distributed storage.

### 3. Semantic Graph & Search (`/semantic`)
Execute semantic queries using the LanceDB vector database.

*   `POST /semantic/query` — Main endpoint for semantic search. Accepts a text query, generates an embedding, and returns a list of the closest vectors (K-Nearest Neighbors) with content metadata.
*   `POST /semantic/validate_uniqueness` — Check text uniqueness based on semantic proximity to existing records in the network (spam and duplicate prevention).
*   `GET /semantic/cluster/{hash_id}` — Retrieve a cluster of semantically similar objects for a specific record.
*   `POST /semantic/feed` — Generate a personalized feed based on an array of user interest vectors.
*   `GET /semantic/namespace/{namespace_name}` — Fetch semantic data within a specific namespace (e.g., a specific dApp).

### 4. Knowledge Topology (`/graph`)
Navigate connections between objects (replies, citations, hierarchy).

*   `POST /graph/edge` — Create a directed edge between two nodes (e.g., a comment to a post).
*   `GET /graph/edges/outbound/{hash_id}` — Retrieve outbound links (objects this object refers to).
*   `GET /graph/edges/inbound/{hash_id}` — Retrieve inbound links (who refers to this object).
*   `GET /graph/tree/{hash_id}` — Recursively fetch the graph tree (e.g., comment tree).

### 5. Dynamic CRDT State (`/crdt`)
Work with mutable states without centralized locks.

*   `POST /crdt/mutate` — Apply a CRDT operation (e.g., `add`, `remove` for `OR-Set` or update registry).
*   `GET /crdt/{object_id}` — Retrieve the current consistent state of a CRDT object.
*   `POST /crdt/webhook` — Register a webhook to track changes in specific CRDT objects.

### 6. Node Administration (`/node`)
Monitor and configure the local node.

*   `GET /node/health` — Check the liveness status of Rust and Python components.
*   `GET /node/metrics` — Export metrics (number of connected peers, mempool size, PBFT latency, memory utilization).
*   `GET /node/peers` — List of active P2P connections and their addresses (Multiaddr).
*   `POST /node/commercial/api_key` — Generate API keys to restrict node access (for commercial solutions).

---

## Communication Protocol (Protobuf)

All data transmitted over the network is strictly typed. The main structures are defined in `proto/feedo.proto`.

### Main Data Structures

1.  **`FeedoBroadcast`**: The base container for transferring content. Contains the author's public key, object hash, size, signature, and optional metadata.
2.  **`PbftMessage`**: Used for communication between nodes during consensus (Pre-Prepare, Prepare, Commit).
3.  **`CrdtOperation`**: Defines the delta of changes to synchronize the CRDT state.

---

## Deployment & Setup

Docker is used to deploy a full-fledged node. The system automatically spins up the Rust core, Python backend, and necessary databases.

### Running via Docker (Recommended)

The easiest way to start a node is to use the ready-made configurations. Depending on your goals, you can run a standard node or a hybrid node acting as a bridge.

To run a standard node:
```bash
docker-compose up -d
```

To run a **Nostr Hybrid Node** (bridging Nostr relays to Feedo):
```bash
docker-compose -f docker-compose.nostr.yml up -d
```

To run a **Farcaster Hybrid Node** (bridging Farcaster Hubs to Feedo):
```bash
docker-compose -f docker-compose.farcaster.yml up -d
```

### Local Build (For Developers)

If you want to modify the protocol code:

```bash
# Clone the repository
git clone https://github.com/your-org/feedo.git
cd feedo/feedo

# Start the node with a source code build
docker-compose up --build
```

### Initialization

After starting, the node automatically:
1.  Generates a new ED25519 key pair if missing (however, it is highly recommended to generate your own keys using the 'feedo/generate_keys.py' script and save them to your '.env' file).
2.  Opens a TCP/UDP (QUIC) port for `libp2p`.
3.  Loads `Kademlia` bootstrap addresses.
4.  Creates local directories for the `sled` database and `LanceDB`.

---

## Algorithms & Mechanisms

### 1. Routing (Kademlia DHT)
The protocol uses a distributed hash table to search for content by its `hash_id` or search for nodes by their `NodeId`. This eliminates the need for central index servers.

### 2. Synchronization (Anti-Entropy)
An anti-entropy protocol is used to ensure data consistency. Nodes periodically exchange Merkle Trees of their local databases. When discrepancies are detected, it initiates the downloading of missing blocks (DAG Sync).

### 3. Consensus & Tokenomics (PBFT)
Practical Byzantine Fault Tolerance is used for operations requiring strict ordering and finalization (DID registration, balance transfers, CRDT rights changes). Validator nodes pass through `Pre-Prepare`, `Prepare`, and `Commit` phases, forming a cryptographic proof of transaction completion. Validators are rewarded via an EVM-based smart contract mechanism (`FeedoPayment.sol`), supporting micro-transactions and automatic claiming using Merkle Roots.

<br>
<br>

---

<a name="feedo-protocol-uk"></a>
# Feedo Protocol (UK)

Feedo — це Універсальний Семантичний Шар для децентралізованого інтернету (нехай це буде Web4, хаха). Головна ідея — створення фундаментального протоколу та базової інфраструктури, на якій розробники будуть будувати нові додатки (dApps) майбутнього. Це нативний базовий шар даних зі стійкою до цензури P2P-мережею та AI-пошуком за сенсом.

Але щоб подолати проблему "порожньої мережі" і швидко вийти на ринок (Go-To-Market), Feedo на початковому етапі "заковтує" дані з уже існуючих розрізнених мереж (Nostr, Farcaster). Це наповнює глобальний граф життям з першого ж дня, дозволяє знаходити контент за його **сенсом** і створює ідеальний ґрунт для нових проектів.

## Технологічний Стек

*   **P2P Core (Низькорівневе ядро):** Rust, `libp2p` (Gossipsub, Kademlia DHT), `sled` (key-value storage).
*   **Консенсус та Стан:** PBFT (Practical Byzantine Fault Tolerance), CRDT (Conflict-free Replicated Data Types).
*   **Semantic API (Прикладний рівень):** Python, `FastAPI`, `SentenceTransformers`, `LanceDB` (Vector DB), `SQLAlchemy` (SQLite).
*   **Смарт-Контракти (Токеноміка):** Solidity (EVM) для виплат PBFT-валідаторам та мікротранзакцій.
*   **Серіалізація та IPC:** Protocol Buffers (`protobuf`), gRPC.
*   **Клієнтський рівень:** SDK (Python, Rust, TS), Flutter (Web/Mobile Explorer).

---

## Архітектурний Дизайн

Архітектура протоколу базується на розділенні функцій мережевої взаємодії та семантичної обробки даних:

1.  **Feedo Core (Rust):** Забезпечує мережевий транспорт. Використовує `libp2p` для встановлення з'єднань між нодами, управління DHT-таблицями маршрутизації та обміну повідомленнями через Gossipsub. Також реалізує логіку консенсусу PBFT для підтвердження транзакцій та зберігає локальний стан у `sled`.
2.  **Feedo API (Python):** Виконує роль семантичного індексатора. Контент, який надходить з P2P-мережі або від клієнтських додатків, векторизується (перетворюється у семантичні ембеддінги) та зберігається у векторній базі даних `LanceDB`. Це забезпечує можливість виконання семантичних запитів.
3.  **Протокольні Мости (Гібридні Ноди):** Feedo може працювати як "гібридна нода" для існуючих децентралізованих мереж. Ми вже нативно підтримуємо мости для **Nostr** (через WebSocket Relay) та **Farcaster** (через gRPC Hub). Повідомлення з цих мереж автоматично транслюються, семантично індексуються і зберігаються у глобальній мережі Feedo.
4.  **Міжпроцесна взаємодія (IPC):** Компоненти на Rust та Python комунікують локально з використанням бінарних `protobuf`-схем (визначених у `feedo.proto`), що мінімізує оверхед на серіалізацію.

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

Для розгортання повноцінної ноди використовується Docker. Система автоматично піднімає ядро на Rust, бекенд на Python та необхідні бази даних.

### Запуск через Docker (Рекомендовано)

Найпростіший спосіб запустити ноду — використати готові конфігурації. В залежності від ваших цілей, ви можете підняти стандартну ноду, або гібридну ноду-міст.

Для запуску стандартної ноди:
```bash
docker-compose up -d
```

Для запуску **Гібридної Ноди Nostr** (яка транслює дані з Nostr у Feedo):
```bash
docker-compose -f docker-compose.nostr.yml up -d
```

Для запуску **Гібридної Ноди Farcaster** (яка транслює дані з Farcaster у Feedo):
```bash
docker-compose -f docker-compose.farcaster.yml up -d
```

### Локальна збірка (Для розробників)

Якщо ти хочеш модифікувати код протоколу:

```bash
# Клонування репозиторію
git clone https://github.com/your-org/feedo.git
cd feedo/feedo

# Запуск ноди зі збіркою з вихідного коду
docker-compose up --build
```

### Ініціалізація

Після запуску нода автоматично:
1.  Генерує нову пару ключів ED25519, якщо вона відсутня (проте, наполегливо рекомендується генерувати власні ключі за допомогою скрипта 'feedo/generate_keys.py' та зберігати їх у '.env' файлі).
2.  Відкриває порт TCP/UDP (QUIC) для `libp2p`.
3.  Завантажує `Kademlia` bootstrap-адреси.
4.  Створює локальні директорії для `sled` бази та `LanceDB`.

---

## Алгоритми та Механізми

### 1. Маршрутизація (Kademlia DHT)
Протокол використовує розподілену хеш-таблицю для пошуку контенту за його `hash_id` або пошуку нод за їхнім `NodeId`. Це усуває необхідність у центральних індексних серверах.

### 2. Синхронізація (Anti-Entropy)
Для забезпечення узгодженості даних використовується протокол анти-ентропії. Ноди періодично обмінюються деревами Меркла (Merkle Trees) своїх локальних баз. При виявленні розбіжностей ініціюється довантаження відсутніх блоків (DAG Sync).

### 3. Консенсус та Токеноміка (PBFT)
Для операцій, що потребують суворого порядку та фіналізації (реєстрація DID, переказ балансів, зміна CRDT-прав), використовується Practical Byzantine Fault Tolerance. Ноди-валідатори проходять фази `Pre-Prepare`, `Prepare` та `Commit`, формуючи криптографічний доказ завершення транзакції. Винагорода валідаторам виплачується через механізм смарт-контрактів (`FeedoPayment.sol`), що підтримує мікротранзакції та автовиплати на основі дерев Меркла.
