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

- [x] **E1.** Створити `server/utils/vectorDbProviders/feedo/index.js`
  - [x] Клас `FeedoDb extends VectorDatabase`
  - [x] `connect()` — створення `FeedoClient` з privateKey
  - [x] `heartbeat()` — перевірка живості
  - [x] `namespaceCount(namespace)` — через `countByNamespace()`
  - [x] `addDocumentToNamespace(namespace, documentData, fullFilePath, skipCache)` — через `indexPrivateDocument()`, docId як hash_id
  - [x] `performSimilaritySearch({...})` — через `search()` з namespace, фільтрація по similarityThreshold
  - [x] `curateSources(sources)` — стандартний мапінг метаданих
  - [x] `deleteDocumentFromNamespace(namespace, docId)` — через `unpin(docId)`
  - [x] `deleteVectorsInNamespace(namespace)` — через `deleteByNamespace()`
  - [x] `reset()` — логування (індивідуальне видалення через `delete-namespace`)

- [x] **E2.** Зареєструвати провайдера
  - [x] `server/utils/helpers/index.js` — `case "feedo"` у `getVectorDbClass` + JSDoc
  - [x] `server/utils/helpers/updateENV.js` — `"feedo"` у `supportedVectorDB`
  - [x] `updateENV.js` — конфіг `FeedoPrivateKey` → `FEEDO_PRIVATE_KEY`
  - [x] `server/models/systemSettings.js` — `FeedoPrivateKey` в `vectorDBPreferenceKeys`
  - [x] `docker/.env.example` — секція Feedo з `VECTOR_DB=feedo` та `FEEDO_PRIVATE_KEY`

- [x] **E3.** Фронтенд
  - [x] Додати Feedo у випадаючий список векторних БД (`VECTOR_DBS`)
  - [x] Створити `frontend/src/components/VectorDBSelection/FeedoDBOptions/index.jsx`
  - [x] Поле `FeedoPrivateKey` (password)
  - [x] Логотип `frontend/src/media/vectordbs/feedo.png` (тимчасовий плейсхолдер)
  - [x] Імпорти у `VectorDatabase/index.jsx`

- [x] **E4.** Перевірка інтеграції (через API-тест + e2e SDK-тест)
  - [x] Запустити AnythingLLM (`VECTOR_DB=feedo`, порт 3001)
  - [x] Створити воркспейс через API
  - [x] Перевірити індексацію документів (namespace = slug, обидві ноди)
  - [x] Перевірити семантичний пошук через API (`performSimilaritySearch`, score 0.87)
  - [x] Перевірити count/delete namespace (`countByNamespace`, `deleteByNamespace`)

- [ ] **E5.** Відкрити PR у AnythingLLM
  - [ ] Закомітити всі зміни
  - [ ] Створити PR з описом (посилання на issue #6113)
  - [ ] Оновити issue #6113 — додати посилання на PR

---

## Фаза F — «Ідея 1»: зберігання документів у Storage Nodes (опційно, поверх векторів)

> **Поточна модель:** Feedo = **text-in** векторне сховище (Feedo ембедить сам через e5-small, зберігає вектори + чанки у Search Nodes). Сирі файли документів лишаються на диску AnythingLLM (`STORAGE_DIR`).

> **Мета «Ідеї 1»:** Feedo = єдиний бекенд — і вектори (Search Nodes), і сирі документи (Storage Nodes). Тоді AnythingLLM стає повністю безсерверним (ні локального диску, ні векторної БД).

### Ключове розуміння: зв'язок «вектор → повний файл» через `docId`

AnythingLLM **вже має** механізм пошуку повного файлу за чанком:

```
Пошук → чанк (вектор + metadata.docId)
   ↓
Document.content(docId)              ← server/models/documents.js (~рядок 286)
   ↓
fileData(document.docpath)           ← читає ПОВНИЙ файл
```

- Чанки зберігаються з `docId` у metadata (наш провайдер це вже робить: `indexDocument(pageContent, { ...metadata, docId }, namespace, docId)`)
- Повний файл береться за `docpath` (шлях на диску), НЕ через вектор

**Точка підключення — одна функція `fileData()` у `server/utils/files/index.js`:**
- Зараз: `docpath = "/server/storage/documents/foo.pdf"` → `fs.readFile` з диску
- Ідея 1: `docpath = "feedo://<CID>"` → читати/писати через `sdk.storage` (Storage Nodes)

### Що змінити (коли вирішимо робити)

- [ ] **F1.** При upload — замість запису на диск: `sdk.storage.upload(file)` → отримати CID → зберегти CID як `docpath`
- [ ] **F2.** У `fileData()` — якщо `docpath` починається з `feedo://` → `sdk.storage.download(CID)` замість `fs.readFile`
- [ ] **F3.** При delete — `sdk.storage.delete(CID)` разом з `unpin(docId)`

### Токеноміка: все сходиться, проблем немає

| Шар | Ціна | Хто платить |
|---|---|---|
| Вектори (Search Nodes) | безкоштовно | — |
| Документи (Storage Nodes) | $20 / TB / місяць | AnythingLLM-юзер |

- Вектори лишаються безкоштовними (як зараз)
- Сирі документи — платні ($20/TB) = **новий дохід**, не проблема
- Розділення чисте: Search Nodes (free) vs Storage Nodes (paid)

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
