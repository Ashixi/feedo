# Feedo × Cheshire Cat — Implementation Plan

> **Статус:** `Draft`
> **Мета:** інтегрувати Feedo як децентралізовану «пам'ять / RAG» у Cheshire Cat AI через офіційну plugin-систему (MadHatter).
> **Репо:** `cheshire-cat-ai/core` (склоновано в `cheshire-cat-core/`)

---

## Що таке Cheshire Cat

**Cheshire Cat AI (Stregatto)** — фреймворк для побудови AI-агентів, позиціонований як *«best framework to learn how AI agents work»*. Основна аудиторія — освіта/дослідження, але багато компаній публікують на ньому агентів у веб.

- **Python + FastAPI**, UI на `:1865`, Swagger на `:1865/docs`.
- **GPL-3.0** (важливо — копілефт).
- **Версія 2 — «unstable alpha»**: повний перепис, ламаються API, не рекомендовано для продакшену (прямо в README).

### Архітектура v2 (що важливо для нас)

| Шар | Що це | Файли |
|---|---|---|
| **MadHatter** | plugin-менеджер (plugins, hooks, endpoints, services) | `src/cat/mad_hatter/mad_hatter.py` |
| **Декоратори плагінів** | `@hook`, `@endpoint`, `@tool` | `src/cat/mad_hatter/decorators/` |
| **Agent / Directive** | цикл агента + механізм підказок | `src/cat/services/agents/base.py` |
| **model_providers** | LLM + embedder як сервіси (`provider:model`) | `src/cat/services/model_providers/` |
| **DB** | **Piccolo ORM (SQL)** — KeyValueDB / UserKeyValueDB / UserScopedDB | `src/cat/db/models.py` |
| **Scaffold plugins** | вбудовані: `chats`, `llms`, `mcp_client`, `ui`, `uploads`, `tutorial` | `src/cat/scaffold/plugins/` |

### 🔑 Головна знахідка: у v2 немає векторної пам'яті в ядрі

У **v1** пам'ять була Qdrant-`VectorMemory`. У **v2 її прибрали з ядра**:
- grep по `qdrant` / `VectorMemory` / `similarity` / `search_points` — **нуль** у core.
- «Пам'ять» тепер = звичайні плагіни (напр. `chats` зберігає розмови в **SQL**-таблиці Piccolo).

Наслідок: **Feedo не впишеться в якийсь готовий «vector store provider»** — такого прошарку більше нема. Замість цього Feedo-плагін **сам відновлює RAG-пам'ять** (як у v1), але поверх Feedo.

### Як у v2 робиться RAG (точка впровадження)

З `src/cat/services/agents/base.py`:
- `Agent.__call__` → `execute_hook("before_agent_run", task)` → `loop()` → `execute_hook("after_agent_run", result)`.
- У `loop()` кожен крок: `self.system_prompt = _base_prompt` → `for d in self.directives: await d.step(self)` → виклик LLM.
- **Формування промпту = задача `Directive`, а не hook** (прямо написано: *"prompt shaping is a directive's job, not a hook's"*).

Тобто класичний RAG-потік («підставити знайдений контекст у системний промпт») = **Directive** з методом `step(agent)`, який кожен хід додає релевантний контекст із Feedo у `agent.system_prompt`.

---

## Підхід

**Feedo = plugin «RAG memory»**, що складається з:

1. **`FeedoRagDirective`** (Service, `service_type="directives"`) — у `step()`:
   - бере останнє повідомлення юзера;
   - `feedo.search.search(query, app_id=...)` → топ-K чанків;
   - додає їх у `agent.system_prompt` («Relevant context: ...»).
2. **Ендпоінти** (`@endpoint`) — залив документів у Feedo, пошук, видалення, статистика.
3. **Settings** (Pydantic-модель) — `search_seeds`, `private_key`, `top_k`, `app_id`.
4. **Ізоляція per-user** — через `app_id` / `metadata` (Cat має мультиюзера).

Feedo = **text-in / text-out** векторне сховище (ембедить сам через e5-small), тому зовнішній embedder Cat нам **не потрібен**: `index_document(content)` і `search(query)` уже ембедять на боці Search Node.

---

## Фаза A — Feedo Python SDK: readiness-чек

Вже є `sdk/python` (пакет `feedo-sdk 0.1.16`, async, `eth_account` для підпису):

- [x] `FeedoClient(search_seeds, consensus_seeds, storage_seeds, private_key)` — `client.py`
- [x] `client.search.index_document(content, metadata)` → `POST /index_document`
- [x] `client.search.search(query, limit, federated, item_type, offset, app_id)` → `GET /query`
- [x] `client.search.get_documents(...)` → `GET /documents`
- [x] `client.search.index_private_document(hash_id, plaintext, metadata)` (E2EE)
- [x] Auth: `X-Feedo-DID` / `X-Feedo-Timestamp` / `X-Feedo-Signature` (`personal_sign` від `FeedoAction:{method}:{path}:{timestamp}`)

- [ ] **A1.** Перевірити, що `search()` підтримує `app_id`-фільтрацію (для per-user ізоляції в Cat).
- [ ] **A2.** Перевірити `namespace`-параметри (чи підтримує `index_document` namespace, як у TS-версії) — якщо ні, додати в Python SDK.
- [ ] **A3.** Визначити дефолтні `search_seeds` для Cat-плагіна (публічні бутстрап-ноди Feedo).
- [ ] **A4.** (опц.) `DELETE` за hash_id для видалення пам'яті (`unpin` є; перевірити видалення саме вектора).

---

## Фаза B — Скелет плагіна `feedo-memory`

Структура (за зразком `scaffold/plugins/chats`):

```
feedo-memory/
├── plugin.json          # name, version, description, min_cat_version "2.0.0"
├── settings.py          # FeedoMemorySettings(BaseModel): seeds, private_key, top_k, threshold, app_id_prefix
├── directive.py         # FeedoRagDirective(Directive): step() -> пошук + апенд у system_prompt
├── endpoints/
│   └── feedo.py         # @endpoint: POST /feedo/ingest, POST /feedo/search, DELETE /feedo/{hash_id}, GET /feedo/count
└── db.py                # (опц.) Piccolo-таблиця лінкування doc -> feedo hash_id (UserScopedDB)
```

- [ ] **B1.** `plugin.json` (маніфест, як у `chats/plugin.json`).
- [ ] **B2.** `settings.py` — Pydantic-модель + `settings_schema()` (dropdown/поля для UI).
- [ ] **B3.** Реєстрація Directive через registry (аналог `service_classes["directives"]`).
- [ ] **B4.** Перевірити механізм завантаження плагіна (`MadHatter.install_plugin` / локальний `PLUGINS_PATH`).

---

## Фаза C — `FeedoRagDirective` (recall / RAG-ін'єкція)

- [ ] **C1.** `step(agent)`: дістати текст останнього `Message` юзера з `agent.task.messages`.
- [ ] **C2.** Виклик `await feedo.search.search(text, limit=top_k, app_id=user_app_id)`.
- [ ] **C3.** Відфільтрувати за `threshold` (якщо SDK повертає score/відстань).
- [ ] **C4.** Сформувати блок контексту і **апенднути** в `agent.system_prompt` (не затерти базовий).
- [ ] **C5.** Обробити помилки мережі (якщо Feedo недоступний — продовжити без контексту, не впасти).
- [ ] **C6.** `app_id = f"ccat:{user_id}"` (із `cat.auth` ambient user), щоб кожен юзер мав свою пам'ять.

---

## Фаза D — Ендпоінти (ingest / search / delete)

- [ ] **D1.** `POST /feedo/ingest` — `{ text, metadata? }` → `feedo.search.index_document(...)`, повертає `hash_id`.
- [ ] **D2.** `POST /feedo/search` — `{ query, limit? }` → `feedo.search.search(...)`.
- [ ] **D3.** `DELETE /feedo/{hash_id}` — видалення чанка з пам'яті.
- [ ] **D4.** `GET /feedo/stats` — кількість/статус (через `get_documents` / `get_stats`).
- [ ] **D5.** Усі роути — `role="authenticated"` і скоуп до ambient `user` (як у `chats/endpoints/crud.py`).

---

## Фаза E — Memory-store (опц., запис розмов у Feedo)

- [ ] **E1.** Hook `after_agent_run` (або `step` директив) — зберігати значущі факти з діалогу в Feedo (`index_document`), щоб агент «запам'ятовував».
- [ ] **E2.** Обмежити обсяг (лише user-повідомлення, дедуплікація за hash_id).

---

## Фаза F — Тести + issue + PR

Cheshire Cat friendly до внесків, але **issue-first** (з `readme/CONTRIBUTING.md`):

- [ ] **F1.** Юніт-тести (pytest): мок `FeedoClient`, перевірити що `step()` правильно формує промпт; тести ендпоінтів.
- [ ] **F2.** `uv run ruff check` + `uv run pytest`.
- [ ] **F3.** Відкрити **issue** з пропозицією Feedo-плагіна (за правилом «only send a PR if you have an assigned issue»).
- [ ] **F4.** Після призначення issue — PR на `main`.
- [ ] **F5.** Врахувати, що код **GPL-3.0**: PR в Cat стає GPL; сам Feedo (MIT) це не зачіпає, але плагін-код — GPL.

---

## Порядок виконання

1. **A1–A4** — readiness Python SDK (має бути швидко, SDK готовий).
2. **B** — скелет плагіна.
3. **C** — RAG-Directive (ядро цінності).
4. **D** — ендпоінти.
5. **E** — memory-store (опц.).
6. **F** — тести + issue → PR.

---

## Відкриті питання / ризики

- **v2 = unstable alpha.** API (Directive/hook назви, registry, settings) можуть ламатись між комітами. План прив'язаний до коміту `2026-07-29`. При реалізації — зафіксувати версію.
- **GPL-3.0.** Якщо плагін має лишатись MIT — тримати його **поза** репо Cat (окреме репо `feedo/cheshire-cat-memory`), а в Cat PR давати лише мінімальну обв'язку або посилання на registry-плагін.
- **Точні імена hook/directive** (`before_agent_run`, `after_agent_run`, `step`) — підтвердити проти актуального `base.py` на момент реалізації.
- **Per-user ізоляція** — підтвердити, що `app_id` у Feedo-пошуку реально фільтрує (якщо ні — використати `metadata.user_id` + фільтр на боці Cat).
- **Score/threshold** — чи повертає `/query` відстань/score для порогової фільтрації (інакше беремо просто top-K).

