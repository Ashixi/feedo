# Feedo × AnythingLLM — Implementation Plan

> **Статус:** `In Progress`
> **Мета:** щоб провайдер AnythingLLM міг реалізувати методи `namespaceCount`, `deleteVectorsInNamespace`, `addDocumentToNamespace` і `performSimilaritySearch` з ізоляцією даних за воркспейсами.

**Варіант Б:** `namespace` зберігається в `metadata` (JSON-рядок) при індексації, фільтрується при пошуку/видаленні/підрахунку.

---

## Фаза A — Search-node (Python)

- [x] **A1.** `main.py` — приймати `namespace` при індексації
  - [x] Додати поле `namespace: str = ""` у `IndexDocumentPayload`
  - [x] Додати поле `namespace: str = ""` у `IndexImagePayload`
  - [x] Додати поле `namespace: str = ""` у `IndexVectorPayload` (P2P)
  - [x] У `POST /index_document` — записувати namespace у metadata
  - [x] У `POST /index_image` — записувати namespace у metadata
  - [x] У `POST /p2p/index_vector` — записувати namespace у metadata

- [x] **A2.** `main.py` — фільтр `namespace` при пошуку та списку документів
  - [x] У `GET /query` — додати параметр `namespace`
  - [x] У `GET /query` — додати SQL-умову фільтрації по metadata
  - [x] У `GET /documents` — додати параметр `namespace`
  - [x] У `GET /documents` — додати SQL-умову фільтрації по metadata

- [x] **A3.** `main.py` — нові ендпоінти
  - [x] `GET /count?namespace=...` — повертає `{ count: N }`
  - [x] `DELETE /namespace/{namespace}` — масове видалення всіх векторів з заданим namespace

- [x] **A4.** `vector_service.py` — допоміжні методи
  - [x] Метод `count_by_namespace(namespace) -> int`
  - [x] Метод `delete_by_namespace(namespace) -> int`
  - [x] Перевірити, чи `delete_vector_async(hash_id)` вже покриває видалення за hash_id

---

## Фаза A5 — Глобальна карта namespace (обов'язково)

- [x] **A5.1.** `p2p.py` — федеративні методи
  - [x] Метод `federated_count(namespace)` — broadcast на всіх пірів `GET /count?namespace=...`, агрегує суму
  - [x] Метод `federated_delete(namespace)` — broadcast на всіх пірів `DELETE /namespace/{namespace}`, агрегує `{deleted: N}`
  - [x] Обмеження TTL для федеративних запитів (аналогічно `federated_search`)

- [x] **A5.2.** `main.py` — ендпоінти з федерацією
  - [x] `GET /count` — локальний count + федеративний broadcast, повертає `{ count: local + peers }`
  - [x] `DELETE /namespace/{namespace}` — локальне видалення + федеративний broadcast на пірів, повертає агрегований `{deleted: N}`

- [x] **A5.3.** `vector_service.py` — розширення `global_knowledge_map`
  - [x] При `add_vector_*` — якщо в metadata є namespace, оновлювати карту: кластер → множина namespace
  - [x] У формат `global_knowledge_map` додати поле `namespaces: list[str]` поруч із `centroid` та `cluster_id`
  - [x] При handshake — передавати `namespaces` у `HandshakePayload`
  - [x] При отриманні handshake — оновлювати `global_knowledge_map` з `namespaces`
  - [x] Нові вектори з невідомим namespace — нормально, карта перебудується при наступному KMeans/центроїд оновленні

- [x] **A5.4.** Маршрутизація з урахуванням namespace
  - [x] `federated_search` — не питати пірів, які не мають жодного namespace з запитуваним
  - [x] `route_query` — якщо відомий namespace, обирати лише ноди, що його містять (фолбек — всі, як зараз)

---

## Фаза B — TypeScript SDK (`sdk/typescript`)

- [x] **B1.** `src/modules/search.ts` — розширити методи
  - [x] `search(...)` — додати параметр `namespace`
  - [x] `indexDocument(...)` — додати параметр `namespace`
  - [x] `getDocuments(...)` — додати параметр `namespace`
  - [x] `indexPrivateDocument(...)` — додати параметр `namespace`
  - [x] `indexImage(...)` — додати параметр `namespace`
  - [x] Додати `countByNamespace(namespace, federated?)` → `GET /count?namespace=...`
  - [x] Додати `deleteByNamespace(namespace)` → `DELETE /namespace/{namespace}`

- [x] **B2.** Перезібрати SDK
  - [x] `npm run build` — без помилок
  - [x] Перевірити, що `.d.ts` оновилися — всі сигнатури на місці

- [x] **B3.** Опублікувати в npm
  - [x] `npm version patch` → `0.1.16`
  - [x] `npm publish` → опубліковано
  - [x] `npm view feedo-protocol-sdk version` → `0.1.16`

---

## Фаза C — Python SDK (`sdk/python`) — опціонально

- [ ] **C1.** Оновити аналогічно TypeScript SDK (якщо є SearchModule)
  - [ ] Не критично для AnythingLLM — можна відкласти

---

## Фаза D — Оновити гайд `FEEDO_ANYTHINGLLM_INTEGRATION.md`

- [x] **D1.** Оновити сигнатури SDK-методів у розділі "Ресурси"
  - [x] Версія SDK: `^0.1.15` → `^0.1.16`
  - [x] Повний перелік методів `search.ts` з параметрами `namespace`
  - [x] Додано `countByNamespace`, `deleteByNamespace`, `unpin`
- [x] **D2.** Оновити каркас провайдера:
  - [x] `addDocumentToNamespace` — `sdk.search.indexDocument(content, metadata, namespace)`
  - [x] `performSimilaritySearch` — `sdk.search.search(input, topN, ..., namespace)`
  - [x] `namespaceCount` — `sdk.search.countByNamespace(namespace)`
  - [x] `deleteVectorsInNamespace` — `sdk.search.deleteByNamespace(namespace)`
  - [x] `deleteDocumentFromNamespace` — `sdk.search.unpin(docId)`

---

## Фаза E — Провайдер AnythingLLM

- [ ] **E1.** Створити `server/utils/vectorDbProviders/feedo/index.js`
  - [ ] Клас `FeedoDb extends VectorDatabase`
  - [ ] `connect()` — створення `FeedoClient` з privateKey
  - [ ] `heartbeat()`
  - [ ] `namespaceCount(namespace)`
  - [ ] `addDocumentToNamespace(namespace, documentData, fullFilePath, skipCache)`
  - [ ] `performSimilaritySearch({...})`
  - [ ] `curateSources(sources)`
  - [ ] `deleteDocumentFromNamespace(namespace, docId)`
  - [ ] `deleteVectorsInNamespace(namespace)`
  - [ ] `reset()`

- [ ] **E2.** Зареєструвати провайдера
  - [ ] `server/utils/helpers/index.js` — `case "feedo"` у `getVectorDbClass`
  - [ ] `server/utils/helpers/updateENV.js` — `"feedo"` у `supportedVectorDB`
  - [ ] `updateENV.js` — конфіг `FeedoPrivateKey` → `FEEDO_PRIVATE_KEY`
  - [ ] Перевірити `docker/.env.example`

- [ ] **E3.** Фронтенд
  - [ ] Додати Feedo у випадаючий список векторних БД
  - [ ] Створити `frontend/src/components/VectorDBSelection/FeedoDBOptions/index.jsx`
  - [ ] Поле `FeedoPrivateKey` (password)

- [ ] **E4.** Перевірка інтеграції
  - [ ] Запустити AnythingLLM
  - [ ] Обрати Feedo, ввести приватний ключ
  - [ ] Створити воркспейс, додати документи через UI
  - [ ] Перевірити індексацію документів
  - [ ] Задати питання в чаті — перевірити семантичний пошук
  - [ ] Перевірити видалення документів/неймспейсів

- [ ] **E5.** Відкрити PR у AnythingLLM
  - [ ] Закомітити всі зміни
  - [ ] Створити PR з описом (посилання на issue #6113)
  - [ ] Оновити issue #6113 — додати посилання на PR

---

## Порядок виконання

1. **A1–A4** — search-node Python (код + деплой на сервери)
2. **B1–B3** — SDK TypeScript (код + build + publish)
3. **D** — оновити гайд
4. **E** — провайдер для AnythingLLM

---

## Відкриті питання

- ~~Чи потрібен `namespace` у `POST /p2p/index_vector` зараз?~~ **Вирішено: потрібен.** Вектори розподілені по мережі (P2P), тому namespace має передаватися при реплікації векторів між нодами.
- Чи видаляє `DELETE /proxy/unpin_feedo/{cid}` вектор і з LanceDB? (Так, за кодом — `brain.delete_vector_async(cid)`.)
