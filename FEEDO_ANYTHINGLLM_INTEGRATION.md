# Feedo × AnythingLLM Integration Guide

Цей документ — покрокова інструкція з реалізації Feedo як нативного vector store провайдера в AnythingLLM.

## Контекст

- **Issue на GitHub:** https://github.com/Mintplex-Labs/anything-llm/issues/6113
- **Репозиторій AnythingLLM (локальний клон):** `anything-llm/`
- **Наше TypeScript SDK:** `sdk/typescript/` (npm-пакет: `feedo-protocol-sdk`, збірка через `tsc`)
- **Мережа Feedo:** P2P vector search + storage. Search Nodes зберігають лише вектори та текстові чанки в LanceDB. Кожен запит підписується ключем користувача (DID).

## Що потрібно зробити

### 1. Додати залежність у `server/package.json`

У `anything-llm/server/package.json` додати наше SDK:

```json
"dependencies": {
  ...,
  "feedo-protocol-sdk": "^0.1.16"
}
```

Потім виконати:

```bash
cd anything-llm/server
npm install
```

> **Альтернатива на час розробки:** замість публікації в npm можна вказати локальний шлях:
> `"feedo-protocol-sdk": "file:../../sdk/typescript"`

---

### 2. Створити `server/utils/vectorDbProviders/feedo/index.js`

Клас `FeedoDb` розширює `VectorDatabase` з `base.js`.

#### Мінімальний каркас:

```javascript
const { FeedoClient } = require("feedo-protocol-sdk");
const { VectorDatabase } = require("../base");

class FeedoDb extends VectorDatabase {
  constructor() {
    super();
    this.sdk = null;
  }

  get name() {
    return "Feedo";
  }

  async connect() {
    if (process.env.VECTOR_DB !== "feedo")
      throw new Error("Feedo::Invalid ENV settings");

    const privateKey = process.env.FEEDO_PRIVATE_KEY;
    if (!privateKey)
      throw new Error("Feedo::FEEDO_PRIVATE_KEY is required");

    if (!this.sdk) {
      this.sdk = new FeedoClient({
        privateKey,
      });
    }
    return { client: this.sdk };
  }

  async heartbeat() {
    await this.connect();
    return { heartbeat: Number(new Date()) };
  }
}

module.exports.FeedoDb = FeedoDb;
```

#### Методи, які потрібно реалізувати (контракт `VectorDatabase`):

| Метод | Призначення | Реалізація через SDK |
|---|---|---|
| `connect()` | Ініціалізація SDK | `new FeedoClient({ privateKey })` |
| `heartbeat()` | Перевірка живості | `this.connect()` |
| `totalVectors()` | Загальна кількість векторів | Опційно, можна `countByNamespace("")` |
| `namespaceCount(namespace)` | Кількість у неймспейсі | `sdk.search.countByNamespace(namespace)` |
| `addDocumentToNamespace(namespace, documentData, fullFilePath, skipCache)` | Індексація документа | `sdk.search.indexDocument(content, metadata, namespace)` |
| `performSimilaritySearch({ namespace, input, LLMConnector, similarityThreshold, topN, filterIdentifiers, rerank })` | Семантичний пошук | `sdk.search.search(input, topN, true, "all", 0, undefined, "text", undefined, namespace)` |
| `deleteDocumentFromNamespace(namespace, docId)` | Видалення документа | `sdk.search.unpin(docId)` — видаляє вектор + файл зі storage |
| `deleteVectorsInNamespace(namespace)` | Очищення неймспейсу | `sdk.search.deleteByNamespace(namespace)` |
| `reset()` | Скидання | Викликати `deleteVectorsInNamespace` для всіх неймспейсів |
| `curateSources(sources)` | Перетворення результатів у формат AnythingLLM | Мапінг полів із відповіді `/query` |

---

### 3. Зареєструвати провайдера

#### `server/utils/helpers/index.js`

У функції `getVectorDbClass` додати новий `case`:

```javascript
case "feedo":
  const { FeedoDb } = require("../vectorDbProviders/feedo");
  return new FeedoDb();
```

Також оновити JSDoc-коментар над функцією:

```javascript
 * @param {('pinecone' | ... | 'astra' | 'pgvector' | 'feedo') | null} getExactly ...
```

#### `server/utils/helpers/updateENV.js`

Додати `"feedo"` у список `supported` у функції `supportedVectorDB`:

```javascript
function supportedVectorDB(input = "") {
  const supported = [
    "chroma", "chromacloud", "pinecone", "lancedb", "weaviate",
    "qdrant", "milvus", "zilliz", "astra", "pgvector", "feedo",
  ];
  ...
}
```

Додати конфігурацію ENV-змінних для Feedo в `updateENV.js` (у секції векторних БД):

```javascript
  // Feedo Options
  FeedoPrivateKey: {
    envKey: "FEEDO_PRIVATE_KEY",
    checks: [isNotEmpty],
  },
```

#### `docker/.env.example` (якщо є)

Додати:

```bash
VECTOR_DB=feedo
FEEDO_PRIVATE_KEY=
```

---

### 4. Фронтенд

#### Випадаючий список: `frontend/src/pages/GeneralSettings/VectorDatabase/index.jsx`

Знайти місце, де перелічені варіанти `LanceDB`, `Pinecone`, і додати `Feedo` у список.

#### Опції провайдера: `frontend/src/components/VectorDBSelection/FeedoDBOptions/index.jsx`

Створити файл аналогічний `LanceDBOptions` або `PineconeDBOptions`:

```jsx
export default function FeedoDBOptions({ settings }) {
  return (
    <div className="w-full flex flex-col gap-y-7">
      <div className="w-full flex items-center gap-[36px] mt-1.5">
        <div className="flex flex-col w-60">
          <label className="text-white text-sm font-semibold block mb-3">
            Feedo Private Key
          </label>
          <input
            type="password"
            name="FeedoPrivateKey"
            className="border-none bg-theme-settings-input-bg text-white placeholder:text-theme-settings-input-placeholder text-sm rounded-lg focus:outline-primary-button active:outline-primary-button outline-none block w-full p-2.5"
            placeholder="Feedo Private Key"
            defaultValue={settings?.FeedoPrivateKey ? "*".repeat(20) : ""}
            required={true}
            autoComplete="off"
            spellCheck={false}
          />
        </div>
      </div>
    </div>
  );
}
```

---

### 5. Перевірка

1. Запустити AnythingLLM.
2. Обрати Feedo у налаштуваннях векторної БД.
3. Ввести приватний ключ.
4. Створити воркспейс, додати документи через UI.
5. Перевірити, що документи індексуються (запити йдуть на search-node).
6. Задати питання в чаті — перевірити семантичний пошук.

## Ключові моменти

- AnythingLLM сам робить ембеддинги через свій `EmbedderEngine` і передає їх як вектори. Але наша search-node **приймає текст** та робить ембеддинг сама. Для простоти можна в `performSimilaritySearch` надсилати `input` (текст) напряму в нашу мережу, ігноруючи `LLMConnector` — так результати будуть семантично консистентні з рештою нашої мережі.
- **Кожен запит до мережі підписується** через `FeedoClient(privateKey)`. Ключ необхідний.
- **Ідентичність клієнта створюється на сайті Feedo** (він сам генерує приватний ключ, публічний ключ і DID). Автогенерація у провайдері не передбачена — юзер вводить готовий приватний ключ.
- При зміні `VECTOR_DB` у `updateENV.js` передбачено `handleVectorStoreReset` — він скидає наявні неймспейси. Це очікувана поведінка при першому налаштуванні.

## Ресурси

- Базовий клас: `anything-llm/server/utils/vectorDbProviders/base.js`
- Приклад реалізації (найближчий): `anything-llm/server/utils/vectorDbProviders/lance/index.js`
- Наше SDK: `sdk/typescript/` (`feedo-protocol-sdk@0.1.16`)
  - `src/client.ts` — `FeedoClient`
  - `src/router.ts` — `NodeRouter` (вибір найшвидшої ноди)
  - `src/modules/search.ts`:
    - `search(query, limit, federated, itemType, offset, appId?, searchType?, imageUrl?, namespace?)` — семантичний пошук із фільтром по namespace
    - `indexDocument(content, metadata, namespace?)` — індексація текстового документа
    - `indexPrivateDocument(hashId, plaintext, metadata, namespace?)` — індексація приватного документа
    - `indexImage(hashId, metadata, symmetricKey?, namespace?)` — індексація зображення
    - `getDocuments(limit, offset, itemType, appId?, namespace?)` — отримання списку документів
    - `countByNamespace(namespace, federated?)` — кількість векторів у неймспейсі
    - `deleteByNamespace(namespace)` — масове видалення векторів неймспейсу
    - `unpin(cid)` — видалення вектора + файлу за hash_id
  - `src/modules/storage.ts` — завантаження файлів
  - `src/modules/crypto.ts` — підпис запитів
