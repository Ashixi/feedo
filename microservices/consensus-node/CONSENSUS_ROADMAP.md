# Consensus Node — Scalability Roadmap / Roadmap масштабування

> 🌐 **Language / Мова**: [🇺🇦 Українська](#uk) | [🇬🇧 English](#en)

<div id="en">

# Consensus Node — Scalability Roadmap

> **Goal**: scale consensus-node from the current ~25-30 nodes to 1,000+ without the "everyone stores everything" model.
>
> **Current problem**: Gossipsub flood — every node receives and processes all transactions, even those not related to its shard or role. This creates O(n²) network load as the number of nodes grows.

---

## Current State (baseline)

| Parameter | Value |
|-----------|-------|
| Confirmed node count | 25 (`test25_output.txt`) |
| Consensus | PBFT (PrePrepare → Prepare → Commit → Finalized) |
| Consensus transport | Gossipsub (flood-based, 6 topics) |
| Committee | 21 validators (reputation-weighted, epoch rotation every 10 min) |
| Transaction types | NameRegistration, UpdateCid, Ledger, DID |
| P2P transport | libp2p (QUIC + TCP), Kademlia DHT, mdns discovery |
| Serialization | Protobuf (prost) + JSON |
| Storage | Sled (embedded) + SQLite (name_db) |
| Smart contract | PporTreasury.sol (Polygon, 2/3+1 multisig) |

---

## Phase 1: Separating Consensus Traffic from Gossip ✅ DONE (2026-07-11)

**Goal**: Direct request-response between validators instead of flood-distribution of PBFT messages via gossipsub.

**Expected growth**: from ~25 to ~50-70 nodes.

**Implemented**:
- `network.rs` — `ConsensusCodec` with `ConsensusRequest`/`ConsensusResponse` enum (TxRelay + PbftVote), protocol `/feedo-consensus/1.0.0`
- `swarm_loop.rs` — `send_pbft_to_committee()`, `self_deliver_pbft_chain()`, `handle_finalized_tx()` (extracted from 5 duplicate handlers), gossipsub fallback for self-only committee
- `main.rs` — `CONSENSUS_DIRECT_MODE=true` flag (default), `ConsensusCodec` integration
- Gossipsub listener for `feedo_consensus_ppor` preserved for backward compatibility (receive), but SEND goes through direct request-response

### What to Change

#### 1.1 `swarm_loop.rs` — replace gossipsub.publish with request_response for `feedo_consensus_ppor`

- **Current code** (lines ~189-209): receives `PbftMessage`, processes via `handle_message()`, and publishes the response to gossipsub via `swarm.behaviour_mut().gossipsub.publish(topic, data)`.
- **What to do**: Replace all `gossipsub.publish` for the `feedo_consensus_ppor` topic with iteration over `current_committee` and sending `request_response.send_request()` to each committee member (except self). This requires a `wallet_address → PeerId` mapping (already available via `peer_announce`).
- **Files**: `swarm_loop.rs` — event handlers for `SwarmEvent::Behaviour(ConsensusBehaviourEvent::Gossipsub(...))` for the `feedo_consensus_ppor` topic, and all places where PBFT response is published.
- **Additionally**: `RelayTxToValidators` already exists (lines ~432-461), which does exactly this for the initial relay — it needs to be extended to all PBFT phases.

#### 1.2 `ppor.rs` — method to get validator PeerIds

- **Current code**: `current_committee` stores `HashSet<String>` wallet addresses, but there is no wallet → PeerId mapping within PporManager.
- **What to do**: Add a method or field that returns a list of PeerIds for the current committee. The `wallet_to_peer` mapping already exists in `swarm_loop.rs` (line 62) — it needs to either be passed to PporManager or kept in one place.
- **Files**: `ppor.rs` — add `get_committee_peers(&self) -> Vec<PeerId>`, `swarm_loop.rs` — update this mapping on each `peer_announce`.

#### 1.3 `network.rs` — extend request-response protocol for all PBFT phases

- **Current code**: `TxRequest` / `TxResponse` for RelayTxToValidators. Only one message type (initial relay).
- **What to do**: Add a new `PbftVote` type to the request-response protocol, containing `PbftMessage` (phase, tx_hash, sender, signature). Replace gossipsub vote distribution with this direct channel.
- **Files**: `network.rs` — new message type in `ConsensusBehaviourEvent`, `swarm_loop.rs` — handler.

#### 1.4 `main.rs` — gossipsub subscription remains only for discovery

- **Current code** (lines ~585-591): subscribes to 7 gossipsub topics.
- **What to do**: Remove subscription to `feedo_consensus_ppor` (or keep for backward compatibility with a flag). Keep: `feedo_peer_announce`, `feedo_name_txs` (temporarily, see phase 2), `feedo_did_updates`.
- **Files**: `main.rs` — lines ~585-591.

### Phase 1 Result

- Gossipsub is used only for discovery and backward compatibility
- Consensus traffic goes directly between committee validators (21 connections instead of flood to all)
- Nodes outside the committee no longer receive or process PBFT messages
- Consensus latency decreases (direct > gossip)

> **⚠️ Phase 1.5 (State pruning) can be done IN PARALLEL with Phase 1** — they don't block each other. Phase 1 changes *how* messages are delivered, Phase 1.5 changes *what* is stored after finalization.

---

## Phase 1.5: State Pruning — Lightweight Nodes ⭐ ✅ DONE (2026-07-11)

**Goal**: New nodes don't download the entire history — only the current state. Moving away from the "blockchain model" of storing all transactions.

**Implemented**:
- `main.rs` — `StateSnapshot` + `NameSnapshotEntry` structures
- `accounting.rs` — `generate_state_snapshot()` (balances + names + Merkle root + secp256k1 signature)
- `name_db.rs` — `get_all_records_full()` for full records with metadata
- `ppor.rs` — `FinalizedArchiveEntry`, `archive_finalized_state()`, `cleanup_finalized_states()` — garbage collection
- `swarm_loop.rs` — `handle_finalized_tx()` calls `archive_finalized_state()`, `epoch_tick` generates snapshot + publishes to DHT (`/snapshot/{epoch}`) + GC
- `replay.rs` — `replay_from_snapshot()` for fast bootstrap (with Merkle root verification)

**Expected growth**: reduced barrier to entry for new nodes (sync in seconds instead of hours), fixed storage size regardless of network age.

**Why this can be done now (without waiting for DAG)**:
- `accounting.rs::generate_merkle_root()` — **already written** (line 63)
- `replay.rs` — **file already exists** (structure ready, implementation needed)
- DHT publishing — **already works** (`PublishDht` in swarm_loop)
- Epoch rotation — **already exists** every 10 minutes (natural snapshot point)
- Gossipsub for discovery — **not needed** for this phase (DHT only)

### What to Change

#### 1.5.1 `accounting.rs` — Merkle-based state snapshot

- **Current code**: Ledger stores balances in HashMap + Sled, `generate_merkle_root()` already exists (line 63).
- **What to do**: Add `generate_state_snapshot(epoch: u64) -> Snapshot` — serializes current state (balances + active names + CID) into a compact format + Merkle root. Snapshot is stored in DHT under the key `/snapshot/{epoch}`. A new node on startup requests the latest snapshot, validates the Merkle root, and loads only transactions after the snapshot.
- **Files**: `accounting.rs` — `generate_state_snapshot()`, `swarm_loop.rs` — publish snapshot to DHT on each epoch rotation, `main.rs` — initialization from snapshot on startup.

#### 1.5.2 `replay.rs` — state reconstruction from snapshot

- **Current code**: `replay.rs` exists but is empty.
- **What to do**: Implement `replay_from_snapshot(snapshot, transactions_since) -> State`:
  1. Load snapshot (balances, names, CID)
  2. Get the list of transactions after snapshot (via DHT `/txs_since/{epoch}` or request-response)
  3. Apply transactions sequentially
  4. Verify Merkle root against the one declared in snapshot
- **Files**: `replay.rs` — full implementation.

#### 1.5.3 `ppor.rs` — garbage collection for finalized transactions

- **Current code**: `PporState` is stored in `HashMap<String, PporState>` indefinitely, only timeout-based removal (`cleanup_timed_out` method).
- **What to do**: After transaction finalization, store only `(tx_hash, finalized_at)` for audit. Full `PporState` (with prepares, commits, committee) is deleted N epochs after finalization. Snapshot contains aggregated state — voting history is not needed by new nodes.
- **Files**: `ppor.rs` — add `archive_finalized_state(tx_hash: &str)`, which moves tx_hash to an archive list and deletes PporState. `swarm_loop.rs` — call after receiving Finalized.

#### 1.5.4 `swarm_loop.rs` — automatic snapshot publishing on epoch rotation

- **What to do**: On each `rotate_epoch()` (every 10 min):
  1. Call `generate_state_snapshot()` for the current state
  2. Publish snapshot to DHT (`/snapshot/{epoch}`)
  3. Keep the last N snapshots (e.g., 3) for availability
  4. Call `archive_finalized_state()` for all transactions finalized in the past epoch
- **Files**: `swarm_loop.rs` — add `SwarmCommand::PublishSnapshot` and call in the Finalized handler.

### Phase 1.5 Result

- A new node syncs in seconds instead of hours (snapshot only + recent transactions)
- Storage size per node is fixed (~10-20 MB regardless of network age)
- Network traffic for synchronization is minimal (snapshot + delta)
- The "everyone stores everything" model is eliminated already in this phase, without waiting for DAG

> **Explanation**: This is **NOT** a blockchain model. Nodes don't store the full transaction history — only the current state (balances, active names with CID) plus a Merkle root for validation. Historical transactions can be deleted after the snapshot. This is similar to how stateless clients work in Ethereum, but without the need for a full blockchain.

---

## Phase 2: Committee Sharding by Transaction Type

**Goal**: Parallel processing of different transaction types by different subcommittees.

**Expected growth**: from ~50-70 to ~150-200 nodes.

### What to Change

#### 2.1 `ppor.rs` — extend `select_committee_weighted` for subcommittees

- **Current code** (lines ~246-274): selects one committee of ≤21 validators based on reputation-weighted scoring.
- **What to do**: Change signature to `select_committee_weighted(&mut self, seed: &str) -> HashMap<i32, HashSet<String>>`, where the key is `tx_type`, value is the subcommittee for that type. Example:
  - General pool: top-63 validators by reputation
  - `TX_TYPE_NAME_REGISTRATION` (3): first 21
  - `TX_TYPE_UPDATE_CID` (4): next 21
  - `TX_TYPE_LEDGER` (5): last 21
  - Or deterministic distribution: `hash(seed || node_id || tx_type) % subcommittee_count`
- **Files**: `ppor.rs` — rewrite `select_committee_weighted()` and add `get_committee_for_tx_type(tx_type: i32) -> HashSet<String>`.

#### 2.2 `ppor.rs` — `TxTimeoutSecs` differentiated by type

- **Current code**: constant `TX_TIMEOUT_SECS: u64 = 30` for all transaction types.
- **What to do**: Different timeouts for different types:
  - NameRegistration: 30 sec (user is waiting)
  - UpdateCid: 10 sec (lightweight operation)
  - Ledger: 60 sec (financial operation, caution needed)
- **Files**: `ppor.rs` — replace constant with method `tx_timeout_for_type(tx_type: i32) -> Duration`.

#### 2.3 `swarm_loop.rs` — relay only to the relevant subcommittee

- **Current code**: `RelayTxToValidators` (lines ~432-461) iterates over the entire `current_committee`.
- **What to do**: On relay, check `tx_type` and send only to validators of the corresponding subcommittee. Gossipsub backups (`feedo_name_txs`, etc.) also publish only to their subcommittee.
- **Files**: `swarm_loop.rs` — modify `RelayTxToValidators`, `BroadcastNameTx`, `BroadcastUpdateCidTx`, `BroadcastLedgerTx`.

### Phase 2 Result

- 3 parallel consensus processes instead of one sequential
- Name registration is not blocked by ledger transactions
- Each validator processes only its own subcommittee
- New transaction types can be added without degrading existing ones

---

## Phase 3: Namespace-Based Sharding for Names

**Goal**: Each validator is responsible only for its own name range, not for all names.

**Expected growth**: from ~150-200 to ~500-1,000 nodes.

### What to Change

#### 3.1 `ppor.rs` — shard-aware committee

- **Current code**: `select_committee_weighted()` does not account for namespace.
- **What to do**: Add `shard_key: &str` parameter to `select_committee_weighted()`. Shard is determined as `sha256(name) % total_shards`. Each shard has its own subcommittee. Number of shards = `total_validators / target_committee_size` (e.g., 100 validators / 21 = ~5 shards). Distribution of validators across shards is deterministic: `hash(seed || node_id || shard_index)`.
- **Files**: `ppor.rs` — modify `select_committee_weighted()`, add `get_shard_for_name(name: &str) -> u64`.

#### 3.2 `name_db.rs` — sharded storage

- **Current code**: SQLite database stores all names (`names` table).
- **What to do**: A node stores only names belonging to its shard(s). On resolve, if the name does not belong to the local shard — query validators of the correct shard. For this:
  - On `insert_name()` check if the name belongs to this shard
  - On `resolve_name()` first check locally, then ask shard validators
- **Files**: `name_db.rs` — add `is_name_in_my_shard(name: &str) -> bool`, `main.rs` — `resolve_name_http` with shard-aware routing.

#### 3.3 `swarm_loop.rs` — shard-aware relay

- **What to do**: On `RelayTxToValidators` for name transactions, determine shard by name and send only to validators of that shard. Gossipsub for `feedo_name_txs` also publish only on shard-specific topic (e.g., `feedo_name_txs_shard_3`).
- **Files**: `swarm_loop.rs` — modify `BroadcastNameTx` and `RelayTxToValidators` for TX_TYPE_NAME_REGISTRATION.

#### 3.4 `main.rs` — shard discovery

- **Current code**: `resolve_name_http` checks locally, then DHT.
- **What to do**: Add logic: if the name is not in the local shard, determine shard → find validators of that shard via DHT → query them directly.
- **Files**: `main.rs` — `resolve_name_http`.

### Phase 3 Result

- Each node stores ~1/N names (where N is the number of shards)
- No "hot" nodes processing all registrations
- Geographic distribution of shards (e.g., European names on European nodes)
- Network traffic proportional to number of shards, not total number of nodes

---

## Phase 4 (Strategic): DAG-Based Mempool + Asynchronous Consensus

**Goal**: Consensus throughput grows linearly with the number of validators.

**Expected growth**: ~10,000+ nodes, TPS grows with the number of validators.

### Concept

Instead of a single leader proposing transactions sequentially (current PBFT), each validator publishes its own block of transactions referencing previous blocks of other validators. This forms a Directed Acyclic Graph (DAG). Consensus is achieved not by voting on each transaction, but by confirming the DAG structure — when enough validators have included a reference to your block, it is considered finalized.

**Analogues**: Narwhal + Bullshark (Aptos, Sui), Tusk, DAG-Rider.

### What to Change

#### 4.1 `ppor.rs` — DAG version instead of PBFT (or new `dag.rs`)

- **What to do**: Add a new `dag.rs` module or extend `ppor.rs`:
  - `DagBlock` — structure: `author`, `round`, `parents: Vec<BlockHash>`, `transactions: Vec<Transaction>`, `signature`
  - `DagMempool` — collection of blocks awaiting finalization
  - `finalize_block(block)` — when a block has enough descendants (2f+1 confirmations), it is finalized
  - Linear ordering of finalized blocks via topological sort
- **Files**: new `dag.rs`, changes in `ppor.rs` — add `ConsensusMode::DAG` mode.

#### 4.2 `swarm_loop.rs` — block broadcast instead of PBFT messages

- **What to do**: Each validator in each round:
  1. Collects transactions from mempool
  2. Forms `DagBlock` with references to previous round blocks
  3. Sends block to other validators via request-response
  4. Receives blocks from others, verifies signatures, adds to local DAG
- **Files**: `swarm_loop.rs` — new event loop for DAG rounds.

#### 4.3 `network.rs` — DAG messages in request-response protocol

- **What to do**: Add message types:
  - `DagBlockProposal` — new block from validator
  - `DagBlockVote` — block confirmation (for Bullshark-style)
  - `DagSyncRequest` — request for missed blocks
- **Files**: `network.rs` — new variants in `ConsensusBehaviourEvent`.

### Phase 4 Result

- TPS scales with the number of validators (more validators = more parallel blocks)
- No single leader — no single point of failure
- Asynchronous model: validators don't wait for each other
- Network overhead: O(n) instead of O(n²) — each validator sends its block to n-1 others, not flood

---

## What NOT to Do

- ❌ **Replicate all transactions to all nodes** — this is the Bitcoin model, it doesn't scale for a search engine
- ❌ **Replace gossipsub with another flood protocol** — the problem is in the "everyone hears everything" approach itself, not in the specific implementation
- ❌ **Switch to Tendermint/Cosmos SDK** — this is overkill, and it's also an "everyone stores everything" model
- ❌ **Delete gossipsub completely** — it's needed for discovery (`feedo_peer_announce`, mdns alternative)

---

## Scalability Summary Table

| Phase | Max Nodes | TPS (estimate) | Finalization Latency | Storage per Node | Approx. Implementation Time |
|-------|-----------|----------------|----------------------|------------------|----------------------------|
| Current (baseline) | 25-30 | ~10 | ~5-10 sec | ~100 MB (grows over time) | — |
| Phase 1 (direct messages) | 50-70 | ~50 | ~2-5 sec | ~100 MB | 1-2 days |
| Phase 1.5 (state pruning) ⭐ | 50-70 | ~50 | ~2-5 sec | ~10-20 MB (fixed) | 3-5 days |
| Phase 2 (tx-type sharding) | 150-200 | ~150 | ~2-5 sec | ~10-20 MB/node | 3-5 days |
| Phase 3 (namespace sharding) | 500-1,000 | ~500 | ~2-5 sec | ~10-20 MB/node | 1-2 weeks |
| Phase 4 (DAG-based) | 10,000+ | ~5,000+ | <1 sec | ~10 MB/node | 3-4 weeks |

> **Explanation**: Storage stops growing after Phase 1.5 — snapshot + Merkle root ensure a fixed size regardless of network age. Before Phase 1.5, storage grows linearly with each transaction.

---

## Priorities by Impact

Recommended implementation order (highest impact first):

1. **Phase 1** — quickest win, minimum changes, maximum growth (direct messages)
2. **Phase 1.5** ⭐ — performed **in parallel** with Phase 1 (independent!), eliminates the "blockchain model" of storing everything
3. **Phase 2** — natural extension of Phase 1, uses the already-implemented request-response mechanism
4. **Phase 3** — key for 1,000+ nodes, but requires rethinking name resolution
5. **Phase 4** — strategic, for the future when current PBFT becomes a bottleneck

---

## Risks and Caveats

- **Phase 1**: Direct request-response requires stable connections. If a validator is offline, the message is not delivered. Retry + fallback to DHT lookup needed.
- **Phase 1.5**: Snapshot must be atomic — if a snapshot is taken during transaction processing, the state will be inconsistent. A short lock is needed during the snapshot. But since a snapshot is taken once every 10 min (epoch rotation), this is acceptable.
- **Phase 2-3**: Deterministic sharding — if the shard is determined incorrectly, the transaction will be lost. Assertion tests on boundary values are needed.
- **Phase 4**: DAG requires round synchronization (clock). Without NTP or a BFT clock, there may be issues with block ordering.

</div>

<div id="uk">

# Consensus Node — Roadmap масштабування

> **Мета**: масштабувати consensus-node з поточних ~25-30 нод до 1,000+ без моделі «всі зберігають все».
>
> **Актуальна проблема**: Gossipsub flood — кожна нода отримує та обробляє всі транзакції, навіть ті, що не стосуються її шарду чи ролі. Це дає O(n²) навантаження на мережу при зростанні кількості нод.

---

## Поточний стан (baseline)

| Параметр | Значення |
|----------|----------|
| Підтверджена кількість нод | 25 (тест `test25_output.txt`) |
| Консенсус | PBFT (PrePrepare → Prepare → Commit → Finalized) |
| Транспорт консенсусу | Gossipsub (flood-based, 6 топіків) |
| Комітет | 21 валідатор (reputation-weighted, epoch rotation кожні 10 хв) |
| Типи транзакцій | NameRegistration, UpdateCid, Ledger, DID |
| P2P транспорт | libp2p (QUIC + TCP), Kademlia DHT, mdns discovery |
| Серіалізація | Protobuf (prost) + JSON |
| Сховище | Sled (embedded) + SQLite (name_db) |
| Смарт-контракт | PporTreasury.sol (Polygon, 2/3+1 мультипідпис) |

---

## Фаза 1: Відокремлення consensus-трафіку від gossip ✅ DONE (2026-07-11)

**Ціль**: Прямий request-response між валідаторами замість flood-розсилки PBFT-повідомлень через gossipsub.

**Очікуваний приріст**: з ~25 до ~50-70 нод.

**Реалізовано**:
- `network.rs` — `ConsensusCodec` з enum `ConsensusRequest`/`ConsensusResponse` (TxRelay + PbftVote), протокол `/feedo-consensus/1.0.0`
- `swarm_loop.rs` — `send_pbft_to_committee()`, `self_deliver_pbft_chain()`, `handle_finalized_tx()` (винесено з 5 дублюючих обробників), gossipsub fallback для self-only комітету
- `main.rs` — прапорець `CONSENSUS_DIRECT_MODE=true` (default), інтеграція `ConsensusCodec`
- Gossipsub listener для `feedo_consensus_ppor` збережено для backward compatibility (receive), але SEND йде через direct request-response

### Що змінити

#### 1.1 `swarm_loop.rs` — заміна gossipsub.publish на request_response для `feedo_consensus_ppor`

- **Поточний код** (лінії ~189-209): отримує `PbftMessage`, обробляє через `handle_message()`, і публікує відповідь у gossipsub через `swarm.behaviour_mut().gossipsub.publish(topic, data)`.
- **Що зробити**: Замінити всі `gossipsub.publish` для топіку `feedo_consensus_ppor` на ітерацію по `current_committee` і відправку `request_response.send_request()` до кожного члена комітету (крім себе). Для цього потрібен мапінг `wallet_address → PeerId` (уже є через `peer_announce`).
- **Файли**: `swarm_loop.rs` — обробники подій `SwarmEvent::Behaviour(ConsensusBehaviourEvent::Gossipsub(...))` для топіку `feedo_consensus_ppor`, та всі місця де публікується відповідь PBFT.
- **Додатково**: Уже є `RelayTxToValidators` (лінії ~432-461), який робить саме це для початкового relay — його потрібно розширити на всі фази PBFT.

#### 1.2 `ppor.rs` — метод для отримання PeerId валідаторів

- **Поточний код**: `current_committee` зберігає `HashSet<String>` wallet-адрес, але немає мапінгу wallet → PeerId у межах PporManager.
- **Що зробити**: Додати метод або поле, яке повертає список PeerId для поточного комітету. Мапінг `wallet_to_peer` вже є в `swarm_loop.rs` (лінія 62) — його потрібно або передавати в PporManager, або тримати в одному місці.
- **Файли**: `ppor.rs` — додати `get_committee_peers(&self) -> Vec<PeerId>`, `swarm_loop.rs` — оновлювати цей мапінг при кожному `peer_announce`.

#### 1.3 `network.rs` — розширення request-response протоколу для всіх PBFT-фаз

- **Поточний код**: `TxRequest` / `TxResponse` для RelayTxToValidators. Тільки один тип повідомлення (початковий relay).
- **Що зробити**: Додати новий тип `PbftVote` у request-response протокол, який містить `PbftMessage` (фазу, tx_hash, sender, signature). Замінити gossipsub-розсилку голосів на цей прямий канал.
- **Файли**: `network.rs` — новий тип повідомлення в `ConsensusBehaviourEvent`, `swarm_loop.rs` — обробник.

#### 1.4 `main.rs` — підписка на gossipsub залишається тільки для discovery

- **Поточний код** (лінії ~585-591): підписується на 7 топіків gossipsub.
- **Що зробити**: Прибрати підписку на `feedo_consensus_ppor` (або залишити для backward compatibility з прапорцем). Залишити: `feedo_peer_announce`, `feedo_name_txs` (тимчасово, див. фазу 2), `feedo_did_updates`.
- **Файли**: `main.rs` — рядки ~585-591.

### Результат фази 1

- Gossipsub використовується тільки для discovery та backward compatibility
- Consensus-трафік іде напряму між валідаторами комітету (21 з'єднання замість flood на всіх)
- Ноди поза комітетом більше не отримують і не обробляють PBFT-повідомлення
- Затримка консенсусу зменшується (direct > gossip)

> **⚠️ Фаза 1.5 (State pruning) може виконуватись ПАРАЛЕЛЬНО з Фазою 1** — вони не блокують одна одну. Фаза 1 міняє *як* доставляються повідомлення, Фаза 1.5 міняє *що* зберігається після фіналізації.

---

## Фаза 1.5: State pruning — легковажні ноди ⭐ ✅ DONE (2026-07-11)

**Ціль**: Нові ноди не завантажують всю історію — тільки актуальний стан. Відмова від «блокчейн-моделі» зберігання всіх транзакцій.

**Реалізовано**:
- `main.rs` — структури `StateSnapshot` + `NameSnapshotEntry`
- `accounting.rs` — `generate_state_snapshot()` (баланси + імена + Merkle root + secp256k1 підпис)
- `name_db.rs` — `get_all_records_full()` для повних записів з metadata
- `ppor.rs` — `FinalizedArchiveEntry`, `archive_finalized_state()`, `cleanup_finalized_states()` — garbage collection
- `swarm_loop.rs` — `handle_finalized_tx()` викликає `archive_finalized_state()`, `epoch_tick` генерує snapshot + публікує в DHT (`/snapshot/{epoch}`) + GC
- `replay.rs` — `replay_from_snapshot()` для швидкого bootstrap (з Merkle root верифікацією)

**Очікуваний приріст**: зменшення бар'єру входу для нових нод (синхронізація за секунди замість годин), фіксований розмір сховища незалежно від віку мережі.

**Чому це можна зробити вже зараз (не чекаючи DAG)**:
- `accounting.rs::generate_merkle_root()` — **вже написано** (рядок 63)
- `replay.rs` — **файл уже є** (структура готова, потрібна реалізація)
- DHT публікація — **вже працює** (`PublishDht` у swarm_loop)
- Epoch-rotation — **вже є** кожні 10 хвилин (природна точка для snapshot)
- Gossipsub для discovery — **не потрібен** для цієї фази (тільки DHT)

### Що змінити

#### 1.5.1 `accounting.rs` — Merkle-based state snapshot

- **Поточний код**: Ledger зберігає баланси в HashMap + Sled, `generate_merkle_root()` уже є (лінія 63).
- **Що зробити**: Додати `generate_state_snapshot(epoch: u64) -> Snapshot` — серіалізує поточний стан (баланси + активні імена + CID) у компактний формат + Merkle root. Snapshot зберігається в DHT під ключем `/snapshot/{epoch}`. Нова нода при старті запитує останній snapshot, валідує Merkle root, і дозавантажує тільки транзакції після snapshot.
- **Файли**: `accounting.rs` — `generate_state_snapshot()`, `swarm_loop.rs` — публікація snapshot в DHT при кожному epoch rotation, `main.rs` — ініціалізація з snapshot при старті.

#### 1.5.2 `replay.rs` — відтворення стану з snapshot

- **Поточний код**: `replay.rs` існує, але порожній.
- **Що зробити**: Реалізувати `replay_from_snapshot(snapshot, transactions_since) -> State`:
  1. Завантажити snapshot (баланси, імена, CID)
  2. Отримати список транзакцій після snapshot (через DHT `/txs_since/{epoch}` або request-response)
  3. Застосувати транзакції послідовно
  4. Звірити Merkle root із заявленим у snapshot
- **Файли**: `replay.rs` — повна реалізація.

#### 1.5.3 `ppor.rs` — garbage collection для фіналізованих транзакцій

- **Поточний код**: `PporState` зберігається в `HashMap<String, PporState>` безстроково, тільки таймаут-видалення (метод `cleanup_timed_out`).
- **Що зробити**: Після фіналізації транзакції зберігати тільки `(tx_hash, finalized_at)` для аудиту. Повний `PporState` (з prepares, commits, committee) видаляти через N епох після фіналізації. Snapshot містить агрегований стан — історія голосувань не потрібна новим нодам.
- **Файли**: `ppor.rs` — додати `archive_finalized_state(tx_hash: &str)`, який переносить tx_hash у архівний список і видаляє PporState. `swarm_loop.rs` — викликати після отримання Finalized.

#### 1.5.4 `swarm_loop.rs` — автоматична публікація snapshot при epoch rotation

- **Що зробити**: При кожному `rotate_epoch()` (кожні 10 хв):
  1. Викликати `generate_state_snapshot()` для поточного стану
  2. Публікувати snapshot в DHT (`/snapshot/{epoch}`)
  3. Зберігати останні N snapshot-ів (наприклад, 3) для availability
  4. Викликати `archive_finalized_state()` для всіх транзакцій, фіналізованих у минулій епосі
- **Файли**: `swarm_loop.rs` — додати команду `SwarmCommand::PublishSnapshot` і викликати в обробнику Finalized.

### Результат фази 1.5

- Нова нода синхронізується за секунди замість годин (тільки snapshot + останні транзакції)
- Розмір сховища на ноду фіксований (~10-20 MB незалежно від віку мережі)
- Мережевий трафік для синхронізації мінімальний (snapshot + дельта)
- Модель «всі зберігають все» ліквідується вже на цій фазі, без очікування DAG

> **Пояснення**: Це **НЕ** блокчейн-модель. Ноди не зберігають повну історію транзакцій — тільки актуальний стан (баланси, активні імена з CID) плюс Merkle root для валідації. Історичні транзакції можна видаляти після snapshot-у. Це схоже на те, як працюють stateless клієнти в Ethereum, але без потреби в повному блокчейні.

---

## Фаза 2: Шардинг комітету за типом транзакції

**Ціль**: Паралельна обробка різних типів транзакцій різними підкомітетами.

**Очікуваний приріст**: з ~50-70 до ~150-200 нод.

### Що змінити

#### 2.1 `ppor.rs` — розширення `select_committee_weighted` для підкомітетів

- **Поточний код** (лінії ~246-274): обирає один комітет з ≤21 валідатора на основі reputation-weighted скорингу.
- **Що зробити**: Змінити сигнатуру на `select_committee_weighted(&mut self, seed: &str) -> HashMap<i32, HashSet<String>>`, де ключ — `tx_type`, значення — підкомітет для цього типу. Наприклад:
  - Загальний пул: топ-63 валідатори за reputation
  - `TX_TYPE_NAME_REGISTRATION` (3): перші 21
  - `TX_TYPE_UPDATE_CID` (4): наступні 21
  - `TX_TYPE_LEDGER` (5): останні 21
  - Або детермінований розподіл: `hash(seed || node_id || tx_type) % subcommittee_count`
- **Файли**: `ppor.rs` — переписати `select_committee_weighted()` і додати `get_committee_for_tx_type(tx_type: i32) -> HashSet<String>`.

#### 2.2 `ppor.rs` — `TxTimeoutSecs` диференційований за типом

- **Поточний код**: константа `TX_TIMEOUT_SECS: u64 = 30` для всіх типів транзакцій.
- **Що зробити**: Різні таймаути для різних типів:
  - NameRegistration: 30 сек (користувач чекає)
  - UpdateCid: 10 сек (легка операція)
  - Ledger: 60 сек (фінансова операція, потрібна обережність)
- **Файли**: `ppor.rs` — замінити константу на метод `tx_timeout_for_type(tx_type: i32) -> Duration`.

#### 2.3 `swarm_loop.rs` — релей тільки до релевантного підкомітету

- **Поточний код**: `RelayTxToValidators` (лінії ~432-461) ітерує по всьому `current_committee`.
- **Що зробити**: При relay дивитися на `tx_type` і відправляти тільки валідаторам відповідного підкомітету. Gossipsub-бекапи (`feedo_name_txs`, тощо) теж публікувати тільки на свій підкомітет.
- **Файли**: `swarm_loop.rs` — змінити `RelayTxToValidators`, `BroadcastNameTx`, `BroadcastUpdateCidTx`, `BroadcastLedgerTx`.

### Результат фази 2

- 3 паралельні консенсус-процеси замість одного послідовного
- Name-реєстрація не блокується ledger-транзакціями
- Кожен валідатор обробляє тільки свій підкомітет
- Можна додавати нові типи транзакцій без деградації існуючих

---

## Фаза 3: Namespace-based шардинг для імен

**Ціль**: Кожен валідатор відповідає тільки за свій діапазон імен, а не за всі.

**Очікуваний приріст**: з ~150-200 до ~500-1,000 нод.

### Що змінити

#### 3.1 `ppor.rs` — shard-aware комітет

- **Поточний код**: `select_committee_weighted()` не враховує namespace.
- **Що зробити**: Додати параметр `shard_key: &str` у `select_committee_weighted()`. Shard визначається як `sha256(name) % total_shards`. Кожен shard має свій підкомітет. Кількість шардів = `total_validators / target_committee_size` (наприклад, 100 валідаторів / 21 = ~5 шардів). Розподіл валідаторів по шардах детермінований: `hash(seed || node_id || shard_index)`.
- **Файли**: `ppor.rs` — змінити `select_committee_weighted()`, додати `get_shard_for_name(name: &str) -> u64`.

#### 3.2 `name_db.rs` — шардоване сховище

- **Поточний код**: SQLite база зберігає всі імена (таблиця `names`).
- **Що зробити**: Нода зберігає тільки імена, що належать до її шарду(ів). При resolve, якщо ім'я не належить локальному шарду — запит іде до валідаторів правильного шарду. Для цього:
  - При `insert_name()` перевіряти, чи ім'я належить цьому шарду
  - При `resolve_name()` спочатку перевіряти локально, потім питати валідаторів шарду
- **Файли**: `name_db.rs` — додати `is_name_in_my_shard(name: &str) -> bool`, `main.rs` — `resolve_name_http` з shard-aware роутингом.

#### 3.3 `swarm_loop.rs` — shard-aware relay

- **Що зробити**: При `RelayTxToValidators` для name-транзакцій визначати shard за іменем і відправляти тільки валідаторам цього шарду. Gossipsub для `feedo_name_txs` теж публікувати тільки на shard-специфічний топік (наприклад, `feedo_name_txs_shard_3`).
- **Файли**: `swarm_loop.rs` — змінити `BroadcastNameTx` і `RelayTxToValidators` для TX_TYPE_NAME_REGISTRATION.

#### 3.4 `main.rs` — shard discovery

- **Поточний код**: `resolve_name_http` дивиться локально, потім DHT.
- **Що зробити**: Додати логіку: якщо ім'я не в локальному шарді, визначити shard → знайти валідаторів цього шарду через DHT → запитати в них напряму.
- **Файли**: `main.rs` — `resolve_name_http`.

### Результат фази 3

- Кожна нода зберігає ~1/N імен (де N — кількість шардів)
- Немає «гарячих» нод, які обробляють всі реєстрації
- Географічний розподіл шардів (наприклад, європейські імена на європейських нодах)
- Мережевий трафік пропорційний до кількості шардів, а не до загальної кількості нод

---

## Фаза 4 (стратегічна): DAG-based мемпул + асинхронний консенсус

**Ціль**: Пропускна здатність консенсусу росте лінійно з кількістю валідаторів.

**Очікуваний приріст**: ~10,000+ нод, TPS росте з кількістю валідаторів.

### Концепція

Замість того щоб один лідер пропонував транзакції послідовно (поточний PBFT), кожен валідатор публікує свій блок транзакцій, який посилається на попередні блоки інших валідаторів. Це утворює Directed Acyclic Graph (DAG). Консенсус досягається не голосуванням за кожну транзакцію, а підтвердженням структури DAG — коли достатня кількість валідаторів включила посилання на твій блок, він вважається фіналізованим.

**Аналоги**: Narwhal + Bullshark (Aptos, Sui), Tusk, DAG-Rider.

### Що змінити

#### 4.1 `ppor.rs` — DAG-версія замість PBFT (або новий `dag.rs`)

- **Що зробити**: Додати новий модуль `dag.rs` або розширити `ppor.rs`:
  - `DagBlock` — структура: `author`, `round`, `parents: Vec<BlockHash>`, `transactions: Vec<Transaction>`, `signature`
  - `DagMempool` — колекція блоків, очікуваних на фіналізацію
  - `finalize_block(block)` — коли блок має достатньо нащадків (2f+1 підтверджень), він фіналізується
  - Лінійне впорядкування фіналізованих блоків через topological sort
- **Файли**: новий `dag.rs`, зміни в `ppor.rs` — додати режим `ConsensusMode::DAG`.

#### 4.2 `swarm_loop.rs` — broadcast блоків замість PBFT-повідомлень

- **Що зробити**: Кожен валідатор у кожному раунді:
  1. Збирає транзакції з мемпулу
  2. Формує `DagBlock` з посиланнями на блоки попереднього раунду
  3. Відправляє блок іншим валідаторам через request-response
  4. Отримує блоки від інших, перевіряє підписи, додає в локальний DAG
- **Файли**: `swarm_loop.rs` — новий event loop для DAG-раундів.

#### 4.3 `network.rs` — DAG-повідомлення в request-response протоколі

- **Що зробити**: Додати типи повідомлень:
  - `DagBlockProposal` — новий блок від валідатора
  - `DagBlockVote` — підтвердження блоку (для Bullshark-стилю)
  - `DagSyncRequest` — запит пропущених блоків
- **Файли**: `network.rs` — нові variant-и в `ConsensusBehaviourEvent`.

### Результат фази 4

- TPS масштабується з кількістю валідаторів (більше валідаторів = більше паралельних блоків)
- Немає єдиного лідера — немає single point of failure
- Асинхронна модель: валідатори не чекають один одного
- Мережевий overhead: O(n) замість O(n²) — кожен валідатор шле свій блок n-1 іншим, а не flood

---

## Що НЕ треба робити

- ❌ **Реплікувати всі транзакції на всі ноди** — це модель біткоїна, вона не масштабується для пошукової системи
- ❌ **Міняти gossipsub на інший flood-протокол** — проблема в самому підході «всі чують все», а не в конкретній імплементації
- ❌ **Переходити на Tendermint/Cosmos SDK** — це overkill, і це теж модель «всі зберігають все»
- ❌ **Видаляти gossipsub повністю** — він потрібен для discovery (`feedo_peer_announce`, mdns-альтернатива)

---

## Підсумкова таблиця масштабованості

| Фаза | Макс. нод | TPS (оцінка) | Latency фіналізації | Сховище на ноду | Приблизний час впровадження |
|------|-----------|---------------|----------------------|-----------------|-------------------------|
| Зараз (baseline) | 25-30 | ~10 | ~5-10 сек | ~100 MB (росте з часом) | — |
| Фаза 1 (direct messages) | 50-70 | ~50 | ~2-5 сек | ~100 MB | 1-2 дні |
| Фаза 1.5 (state pruning) ⭐ | 50-70 | ~50 | ~2-5 сек | ~10-20 MB (фіксовано) | 3-5 днів |
| Фаза 2 (tx-type sharding) | 150-200 | ~150 | ~2-5 сек | ~10-20 MB/нода | 3-5 днів |
| Фаза 3 (namespace sharding) | 500-1,000 | ~500 | ~2-5 сек | ~10-20 MB/нода | 1-2 тижні |
| Фаза 4 (DAG-based) | 10,000+ | ~5,000+ | <1 сек | ~10 MB/нода | 3-4 тижні |

> **Пояснення**: Сховище перестає рости після Фази 1.5 — snapshot + Merkle root забезпечують фіксований розмір незалежно від віку мережі. До Фази 1.5 сховище росте лінійно з кожною транзакцією.

---

## Пріоритети за впливом

Рекомендований порядок впровадження (найбільший impact першим):

1. **Фаза 1** — найшвидша перемога, мінімум змін, максимум приросту (direct messages)
2. **Фаза 1.5** ⭐ — виконується **паралельно** з Фазою 1 (незалежна!), ліквідує «блокчейн-модель» зберігання всього
3. **Фаза 2** — природне розширення фази 1, використовує вже зроблений request-response механізм
4. **Фаза 3** — ключова для 1,000+ нод, але потребує переосмислення name resolution
5. **Фаза 4** — стратегічна, для майбутнього, коли поточний PBFT стане вузьким місцем

---

## Ризики та застереження

- **Фаза 1**: Прямий request-response вимагає стабільних з'єднань. Якщо валідатор offline, повідомлення не доставляється. Потрібен retry + fallback на DHT-пошук.
- **Фаза 1.5**: Snapshot повинен бути atomic — якщо snapshot зроблено під час обробки транзакції, стан буде неконсистентним. Потрібен короткий lock на час snapshot-у. Але оскільки snapshot робиться раз на 10 хв (epoch rotation), це прийнятно.
- **Фаза 2-3**: Детермінований шардинг — якщо шард визначено неправильно, транзакція загубиться. Потрібні assertion-тести на граничних значеннях.
- **Фаза 4**: DAG вимагає синхронізації раундів (годинник). Без NTP або BFT-годинника можливі проблеми з порядком блоків.

</div>