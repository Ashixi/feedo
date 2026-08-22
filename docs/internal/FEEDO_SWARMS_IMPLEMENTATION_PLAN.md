# Feedo × Swarms — Implementation Plan

> **Статус:** `In Progress`
> **Мета:** щоб Swarms-агенти могли використовувати Feedo як **децентралізовану довготривалу пам'ять / векторний бекенд** (замість Qdrant/Chroma/Pinecone). Ідентичність = гаманець (`did:feedo:0x…`), дані E2E-зашифровані, тестнет безкоштовний (500k кредитів).

---

## 0. Що змінилося в Swarms (результат дослідження, важливо)

Swarms на момент інтеграції — **v14.0.0** (гілка `master`, ~7.1k⭐, 5,214 комітів, дуже активний). Архітектура пам'яті змінилася порівняно зі старою версією:

| Компонент | Де живе | Статус |
|---|---|---|
| **Короткочасна пам'ять** | `swarms/structs/conversation.py` → клас `Conversation` | in-memory + опційний файл `MEMORY.md` (persistent_memory). **НЕ змінюємо.** |
| **Довготривала пам'ять** | параметр `long_term_memory` в `Agent(...)` | ⚠️ Приймається, але **в run-лупі фактично не викликається** (лише docstring «Handles RAG query…» + `save()` при autosave). Інтерфейс — duck-typing (`Union[Callable, Any]`). |
| **Векторні бази** | окремий пакет `swarms_memory` (repo `The-Swarm-Corporation/swarms-memory`, 43⭐, MIT) | `QdrantDB`, `ChromaDB`, `PineconeMemory`, `FAISSDB`, `SingleStoreDB`, `WeaviateDB`… |

**Ключовий висновок:** канонічне місце для векторних обгорток тепер — **`swarms_memory`**, а не ядро `swarms`. Приклади в ядрі прямо це підтверджують:

```python
# swarms/examples/single_agent/capabilities/rag/qdrant_rag_example.py
from swarms_memory import QdrantDB

rag_db = QdrantDB(client=client, embedding_model="text-embedding-3-small",
                  collection_name="knowledge_base", n_results=3)
agent = Agent(..., long_term_memory=rag_db)
```

> Тому стратегія інтеграції — **два PR**:
> 1. **PR #1 (основний)** → `swarms-memory`: клас `FeedoDB` (один файл `vector_dbs/feedo.py` + експорт в `__init__.py`).
> 2. **PR #2 (видимість)** → `swarms`: приклад `examples/single_agent/capabilities/rag/feedo_example.py` + рядок у списку інтеграцій документації.

---

## 1. Інтерфейс-контракт (що треба реалізувати)

`swarms_memory` не має жорсткого ABC — це duck-typing за зразком `QdrantDB`. Контракт (з README + прикладів):

| Метод | Сигнатура | Що робить |
|---|---|---|
| `add` | `add(doc: str, metadata: dict = None) -> str` | додати один документ, повернути id |
| `batch_add` | `batch_add(docs: List[str], metadata=None, batch_size=...) -> List[str]` | пакетно, повернути список id |
| `query` | `query(query: str, n_results: int = 3, return_metadata: bool = False) -> List[dict]` | семантичний пошук |
| `delete` | `delete(id: str)` | видалити за id |
| `clear` | `clear()` | очистити все |
| `save`/`load` | `save(path)` / `load(path)` | (опційно) для сумісності з autosave Agent |

Формат результату `query` (як у `QdrantDB`):

```python
[
  {"document": "...", "score": 0.87, "<metadata key>": ...},
  ...
]
```

> **Перевага Feedo:** `embedding_model` НЕ потрібен — Feedo ембедить сам на стороні search-node (e5-small для тексту, CLIP для зображень). Ніяких зовнішніх embedding-API/ключів. Це підкреслюємо в PR-описі.

---

## 2. Mapping Feedo ↔ swarms_memory

| `FeedoDB` метод | Виклик Feedo SDK (`feedo-sdk`) | Ендпоінт search-node |
|---|---|---|
| `add(doc, metadata)` | `client.search.index_document(doc, metadata=meta, namespace=self.ns, hash_id=gen_id)` | `POST /index_document` |
| `add(doc)` (приватно) | `client.search.index_private_document(hash_id, doc, metadata=meta, namespace=self.ns)` | `POST /index_document` (`item_type=private_post`) |
| `query(q, n_results)` | `client.search.search(q, limit=n_results, namespace=self.ns, item_type="all"\|"private_post")` | `GET /query?namespace=...` |
| `delete(id)` | `client.search.delete_document(id)` ← **треба додати** | `DELETE /document/{hash_id}` ← **треба додати** |
| `clear()` | `client.search.delete_by_namespace(self.ns)` | `DELETE /namespace/{namespace}` ✅ вже є |

**Ізоляція:** namespace = `feedo-swarms:{agent_name or DID}` (аналог `feedo-memory:{user}:{tier}` з PraisonAI-інтеграції). Кожен агент/тенант ізольований на спільній мережі.

---

## Фаза A — Feedo SDK + search-node: метод видалення одного документа (закрити gap)

> Це єдиний функціональний gap. Зараз у search-node є `DELETE /namespace/{namespace}` (масово) та `brain.delete_vector_async(hash_id)` (внутрішньо), але **немає HTTP-ендпоінта для видалення одного вектора за `hash_id`**. Робимо аналогічно тому, як AnythingLLM-план додавав namespace-ендпоінти (Фаза A тієї роботи).

- [ ] **A1.** `microservices/search-node/main.py` — додати `DELETE /document/{hash_id}`
  - [ ] Викликати існуючий `await brain.delete_vector_async(hash_id)`
  - [ ] (Опційно) федеративний broadcast на пірів, якщо хочемо видаляти й репліки
  - [ ] Повертати `{"status": "ok", "deleted": N}`

- [ ] **A2.** `sdk/python/feedo/modules/search.py` — метод `delete_document(hash_id: str)`
  - [ ] `return await self._request("DELETE", f"/document/{quote(hash_id, safe='')}")`

- [ ] **A3.** (Опційно) продублювати в TypeScript SDK `sdk/typescript/src/modules/search.ts` — `deleteDocument(hashId)`

- [ ] **A4.** Тест: `index_document` → `delete_document` → `search` не повертає документ.

---

## Фаза B — `swarms_memory`: клас `FeedoDB` (PR #1, основний)

Робоча гілка у форку `The-Swarm-Corporation/swarms-memory` (клонуємо окремо для розробки).

- [ ] **B1.** `swarms_memory/vector_dbs/feedo.py` — один файл, один клас `FeedoDB`
  - [ ] Імпорт `from feedo import FeedoClient` (залежність `feedo-sdk`, оголошуємо як optional extra)
  - [ ] `__init__(self, *, usage_key=None, private_key=None, did=None, namespace="feedo-swarms", n_results=3, private=True)`
    - [ ] `private=True` (дефолт) → `index_private_document` + `item_type="private_post"`
    - [ ] Авторезолв DID з `usage_key` (вже є логіка в `FeedoMemory._resolve_did` — перевикористати)
  - [ ] `add(doc, metadata=None) -> str` (генерує `hash_id`, зберігає id в `self._ids`)
  - [ ] `batch_add(docs, metadata=None, batch_size=...) -> List[str]`
  - [ ] `query(query, n_results=None, return_metadata=False) -> List[dict]` → мапує результати на `{"document", "score", **metadata}`
  - [ ] `delete(id)` → `client.search.delete_document(id)` (з Фази A)
  - [ ] `clear()` → `client.search.delete_by_namespace(self.ns)`
  - [ ] `save(path)` / `load(path)` — persist `namespace` + список id (для сумісності з `Agent` autosave, який викликає `long_term_memory.save(...)`)
  - [ ] Синхронний інтерфейс (обгортка над async SDK через `asyncio.run`/ThreadPool — як у нашому `FeedoMemory`)

- [ ] **B2.** `swarms_memory/__init__.py` — `from swarms_memory.vector_dbs.feedo import FeedoDB` (+ `__all__`)

- [ ] **B3.** `pyproject.toml` — optional dependency group:
  ```toml
  [tool.poetry.extras]
  feedo = ["feedo-sdk"]
  ```

- [ ] **B4.** `tests/vector_dbs/test_feedo.py` — по зразку `tests/vector_dbs/test_qdrant.py`
  - [ ] `add` + `query` повертає документ зі score
  - [ ] `batch_add` повертає список id
  - [ ] `delete(id)` прибирає документ з пошуку
  - [ ] `clear()` очищає namespace
  - [ ] (для CI без мережі — мокаємо `FeedoClient`, як інші тести мокають клієнтів БД)

- [ ] **B5.** README `swarms-memory` — додати Feedo в таблицю RAG-систем + короткий приклад.

**PR #1 опис (шаблон):**

```markdown
## What
Adds FeedoDB — a decentralized vector/memory backend for Swarms.

Feedo (feedo.ink) is a decentralized storage + semantic search network.
Identity is your crypto wallet (did:feedo:0x…) — no accounts, no KYC.
No external embedding API needed: Feedo embeds server-side (e5-small).

## Changes
- swarms_memory/vector_dbs/feedo.py — class FeedoDB (add/batch_add/query/delete/clear)
- __init__.py export + optional extra "feedo"

## Usage
from swarms_memory import FeedoDB
rag = FeedoDB(usage_key="0x…")
agent = Agent(..., long_term_memory=rag)

## How to test
pip install -e ".[feedo]"
feedo init   # register DID (free 500k credits on testnet)
pytest tests/vector_dbs/test_feedo.py
```

---

## Фаза C — `swarms`: приклад + документація (PR #2, видимість)

Ядро `swarms` не чіпаємо (правило мінімальної цінності) — додаємо лише example та рядок у доки.

- [ ] **C1.** `examples/single_agent/capabilities/rag/feedo_example.py`
  - [ ] Повторити структуру `qdrant_rag_example.py`, замінити QdrantDB → FeedoDB
  - [ ] Показати і приватний (`private=True`, дефолт) і публічний режими
  - [ ] Коментарі: DID=гаманець, тестнет безкоштовний

- [ ] **C2.** README / docs — додати Feedo в розділ інтеграцій (vector stores / RAG backends)

- [ ] **C3.** PR #2 з описом за шаблоном (розділ 9.1 загального плану) + прохання: (а) лінк у доки, (б) якщо Swarms анонсують інтеграції — попросити анонс.

---

## 3. Відкриті питання / ризики

1. **`long_term_memory` не викликається в run-лупі ядра.** Наразі RAG-ретрівал у `Agent.run` не імплементований (лише docstring). Це не блокує інтеграцію: `FeedoDB` повністю самодостатній (`add`/`query` викликаються користувачем напряму, як в офіційних прикладах Qdrant). Відзначаємо в PR, що за бажання ядро може знову підхопити `long_term_memory.query(...)` — FeedoDB вже реалізує потрібний контракт.
2. **`delete(id)` потребує Фази A** (нового ендпоінта). Без A1 метод `delete` можна тимчасово реалізувати через namespace-трюк або `NotImplementedError` — але краще зробити A (це наш власний код, низький ризик).
3. **`feedo-sdk` як залежність** — робимо optional extra, щоб не тягнути його всім користувачам swarms-memory.
4. **Embedding** — Feedo ембедить сам, тому `embedding_model` не потрібен. Переконатися, що в README це чітко написано (перевага перед Qdrant/Pinecone).

---

## 4. Definition of Done

- [ ] Фаза A: `DELETE /document/{hash_id}` + `SearchModule.delete_document` працюють, тест зелений
- [ ] Фаза B: `FeedoDB` у `swarms_memory`, експорт, extra, тест, README
- [ ] PR #1 (swarms-memory) відкрито
- [ ] Фаза C: приклад `feedo_example.py` + docs entry у `swarms`
- [ ] PR #2 (swarms) відкрито
- [ ] Оновити `INTEGRATION_PLAN.md` — позначити Swarms PR статусом

---

## 5. Порядок виконання

1. **A1–A4** — delete-ендпоінт у нашому search-node + SDK-метод (наш код, незалежний).
2. **B1–B4** — `FeedoDB` у swarms-memory (клон → гілка → PR).
3. **C1–C3** — приклад + docs у swarms.
4. Паралельно оновити README Feedo (секція «Integrated with»).
