# Feedo × Dify — Implementation Plan

> **Status**: Draft
> **Мета**: інтегрувати Feedo як нативний vector store провайдер у Dify (langgenius/dify).
> **Репозиторій**: локальний клон у `dify/`.

---

## 1. Архітектура Dify (що ми дізналися)

Dify перейшов на **плагінну архітектуру** для векторних БД. Це не «один файл у vdb/», а окремий workspace-пакет на кожен провайдер.

### Структура пакета (на прикладі Chroma)

```
api/providers/vdb/vdb-chroma/
├── pyproject.toml          ← залежності + entry point
├── src/dify_vdb_chroma/
│   ├── __init__.py
│   └── chroma_vector.py    ← ChromaVector(BaseVector) + ChromaVectorFactory(AbstractVectorFactory)
└── tests/
```

### Реєстрація (entry point)

```toml
[project.entry-points."dify.vector_backends"]
chroma = "dify_vdb_chroma.chroma_vector:ChromaVectorFactory"
```

### Базовий інтерфейс `BaseVector` (треба реалізувати)

```python
get_type() -> str                          # VectorType.FEEDO
create(texts, embeddings, **kwargs)        # створити колекцію
add_texts(documents, embeddings, **kwargs) # додати документи + ВЕКТОРИ
text_exists(id) -> bool
delete_by_ids(ids)
delete_by_metadata_field(key, value)
search_by_vector(query_vector, **kwargs)   # пошук по ВЕКТОРУ
search_by_full_text(query, **kwargs)
delete()
```

### Factory

```python
class FeedoVectorFactory(AbstractVectorFactory):
    def init_vector(dataset, attributes, embeddings) -> BaseVector
```

### Ще треба зачепити

| Файл | Зміна |
|---|---|
| `api/core/rag/datasource/vdb/vector_type.py` | додати `FEEDO = "feedo"` |
| `api/pyproject.toml` | додати `dify-vdb-feedo` у workspace |
| `configs/` | `FEEDO_PRIVATE_KEY`, `FEEDO_SEARCH_NODES` |
| `web/` (frontend) | Feedo у виборі векторної БД |

---

## 2. КЛЮЧОВИЙ ВИКЛИК: невідповідність ембеддингу

Це те, чого не було в AnythingLLM. Дивись:

**Dify сам робить ембеддинг** і передає провайдеру **готові вектори**:
```python
provider.add_texts(documents, embeddings)      # embeddings — готові вектори
provider.search_by_vector(query_vector)         # query_vector — готовий вектор
```

**Feedo сам робить ембеддинг** (текст-вхід):
```python
POST /index_document  { text: "..." }   # Feedo ембедить САМ
GET  /query           { text: "..." }   # Feedo ембедить САМ
```

Тобто:
- **Dify**: «ось тобі вектори, збережи і шукай по них»
- **Feedo**: «ось тобі текст, я сам зроблю вектор»

### Проблема

`search_by_vector(query_vector)` дає провайдеру **вектор**, а Feedo для пошуку потребує **текст**. З вектора текст не відновиш.

### Додаткова складність: розмірність

- Feedo: `multilingual-e5-small` = **384-dim** (жорстко в схемі)
- Dify: будь-яка модель (OpenAI = 1536-dim, тощо)

Якщо Dify ембедить 1536-dim, а Feedo чекає 384-dim — вони несумісні.

---

## 3. Два архітектурні варіанти

### Варіант A: «Feedo ембедить сам» (ігноруємо модель Dify)

- `add_texts`: ігноруємо `embeddings`, шлемо `page_content` текст у Feedo → Feedo ембедить (e5-small)
- `search_by_vector`: **проблема** — Dify дає вектор, а нам треба текст
- **Висновок**: не працює чисто, бо `search_by_vector` приймає вектор

### Варіант B: «Dify ембедить, Feedo зберігає вектори» (Feedo = «тупа» vector DB)

- Feedo отримує нові user-facing ендпоінти:
  - `POST /index_vector` — зберегти (text + готовий вектор)
  - `POST /query_vector` — пошук по готовому вектору
- Feedo має підтримувати **довільну розмірність** (або жорстко Dify-модель)
- Dify робить весь ембеддинг, Feedo тільки зберігає/шукає

**Це архітектурно чистіше** (як Pinecone/Chroma — «тупа» vector DB), але потребує змін у Feedo:
- підтримка готових векторів (зараз є тільки P2P-роут `/p2p/index_vector`, не user-facing)
- підтримка довільної розмірності (зараз жорстко 384-dim)

### Варіант C (гібрид): Feedo підтримує обидва режими

- Text-режим (для своїх клієнтів): `/index_document`, `/query` (embedding всередині)
- Vector-режим (для Dify-подібних): `/index_vector`, `/query_vector` (готові вектори)

---

## 4. Рішення (фінальне)

**Два режими для двох типів клієнтів:**

| Клієнт | Режим | Хто ембедить | Що заробляє Feedo |
|---|---|---|---|
| Прямий SDK-юзер | **text-in** | Feedo (e5-small) | embedding + пошук |
| Dify-юзер | **vector-in** | Dify (своя модель) | тільки пошук (дешевший) |

```
Text-in  (прямий юзер): текст → Feedo ембедить → Feedo зберігає → Feedo шукає
Vector-in (Dify):       текст → Dify ембедить → Feedo зберігає вектор → Feedo шукає по вектору
```

- ✅ Без нових моделей: vector-in потребує лише **гнучку схему LanceDB** (довільна розмірність), не нові моделі
- ✅ Ембединг-дохід лишається у Feedo для **прямих** користувачів (text-in)
- ✅ Для Dify Feedo продає **зберігання + пошук + serverless** (ембединг відібрати технічно неможливо — Dify ембедить сам)
- 📌 «Ідея 1» (сирі документи у Storage Nodes) — додаткова фіча поверх, не в першій версії

**Ключове розуміння:** пошук по векторах = чиста математика (косинусна відстань), не модель. Feedo не «розуміє» чужий вектор — він просто зберігає числа і міряє відстань. Єдина умова — запит і збережені вектори однієї розмірності.

---

## 5. Кроки імплементації (Варіант B/C)

### Фаза F1 — Feedo search-node: векторний режим

- [ ] `POST /index_vector` (user-facing) — приймає `{ hash_id, vector, text, metadata, namespace }`
- [ ] `GET /query_vector` — приймає `{ vector, top_k, namespace }`, шукає по вектору
- [ ] LanceDB схема: `vector` довільної розмірності (зараз `pa.list_(pa.float32(), 384)`)
- [ ] Або окрема таблиця `post_vectors_flex` для довільних розмірностей

### Фаза F2 — Dify пакет `dify-vdb-feedo`

- [ ] `api/providers/vdb/vdb-feedo/pyproject.toml` (залежність `feedo-sdk` + entry point)
- [ ] `src/dify_vdb_feedo/feedo_vector.py`:
  - [ ] `FeedoVector(BaseVector)` — всі 9 методів
  - [ ] `FeedoVectorFactory(AbstractVectorFactory)` — `init_vector`
- [ ] `vector_type.py` — `FEEDO = "feedo"`
- [ ] `api/pyproject.toml` — `dify-vdb-feedo` у workspace

### Фаза F3 — Конфіг і фронтенд

- [ ] `configs/` — `FEEDO_PRIVATE_KEY`, `FEEDO_SEARCH_NODES`
- [ ] `web/` — Feedo у виборі векторної БД + поле для ключа
- [ ] `.env.example` — секція Feedo

### Фаза F4 — Тести

- [ ] Unit-тести (як у `vdb-chroma/tests/unit_tests`)
- [ ] Інтеграційний тест проти живої мережі Feedo

---

## 6. Відкриті питання

1. **Розмірність векторів.** Feedo зараз жорстко 384-dim. Підтримувати довільну розмірність чи жорстко прив'язати до однієї моделі?

2. **Чи робити Feedo «тупою» vector DB (Варіант B), чи лишити text-центричною (Варіант A)?** Це впливає на всю майбутню стратегію інтеграцій.

3. **Чи варто взагалі інтегрувати Feedo в Dify, якщо Dify сам ембедить?** Можливо, цінність Feedo тут — децентралізоване ЗБЕРІГАННЯ векторів, а не ембеддинг. Тоді Варіант B єдиний логічний.

4. **`search_by_full_text`** — Dify має повнотекстовий пошук (BM25). Feedo його не має. Повертати порожній список (як Chroma)?

5. **Неймспейс/ізоляція.** Dify використовує `collection_name` (по dataset). Мапуємо його на Feedo `namespace`.

---

## 7. Порядок

1. Вирішити відкрите питання #2 (A vs B) — це блокує все.
2. F1 — Feedo векторний режим (якщо обрали B).
3. F2 — Dify пакет.
4. F3 — конфіг + фронтенд.
5. F4 — тести.

