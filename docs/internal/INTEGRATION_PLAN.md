# Feedo — План дій: інтеграції + токеноміка

> **Принцип:** інтеграції створюють **попит** (користувачі), токеноміка створює **пропозицію** (ноди-оператори). Спершу попит → потім економіка.

---

## Головне питання: коли робити токеноміку?

**Не після конкретного проєкту, а після мілстоуна.** Критерій переходу до повної токеноміки:

- ✅ 3–5 інтеграцій злито в апстрім (реальні PR, не issues)
- ✅ є перші реальні користувачі (хтось встановив і гоняє запити)
- ✅ зрозуміло, які операції реально навантажують мережу

До цього моменту токеноміка **не блокує** жоден PR — перші інтеграції йдуть із безкоштовним тестнетом.

---

## Фаза 0 — Інтеграції без токеноміки (зараз, 2–3 тижні)

**Ціль:** 3–5 злитих PR → доказ, що Feedo працює як memory / vector / RAG бекенд.

**Тактика:** одразу PR (не issues). Прості адаптери, мінімум коду, нуль залежностей від токеноміки.

**Порядок (за анонс-активністю):**
1. **PraisonAI** (Python) — номер один, найбільше анонс-охоплення (ютубер Mervin Praison).
2. **Swarms** (Python) — активний Discord/Twitter/YouTube/Blog.
3. **BeeAI Framework** (Python/TS) — IBM/Linux Foundation, ведуть changelog.
4. **DocsGPT** (Python) — великий, але enterprise.
5. 1 плагін Рівня 2 — **ElizaOS** або **LobeChat** (окремий пакет, нульовий ризик відмови ядра).

> ⚠️ **Daydreams** і **Superagent** — пропустити (півоти: Daydreams пішов в «Agentic Commerce», Superagent став AI-safety SDK).

**Що використовуємо:** SDK (Python+TS), DID = гаманець, usage key, storage, search. Все безкоштовно (тестнет, 500k кредитів на DID).

**Токеноміка:** не потрібна. На питання про оплату відповідь: «поки тестнет безкоштовний, 500k кредитів на реєстрацію».

---

## Фаза 1 — Софт-метринг (після ~3 злитих PR)

**Критерій переходу:** 3+ інтеграцій злито, з'явилися перші користувачі.

**Що робимо (майже все вже є в коді):**
- [ ] Баланс-чек перед платними роутами — розширити існуючий consensus-виклик у `search-node/auth.py` та storage-node
- [ ] Списати кредити за запити/зберігання (ledger уже вміє debit/credit)
- [ ] Rate limit за репутацією DID (тіри Fresh/Active/Verified)

**Це НЕ повна токеноміка** — просто облік використання, без грошей і без оплати.

---

## Фаза 2 — Повна токеноміка (коли є реальний трафік)

**Критерій переходу:** реальний обсяг запитів + потреба залучати ноди-операторів.

**Що робимо:**
- [ ] Топ-ап через контракт `PporTreasury.sol` — `deposit(amount)`, USDC, `msg.sender = DID`
- [ ] Метринг + атрибуція (ingress/storage спліт ~80/20)
- [ ] Cash-out: proof балансу ноди → оператор забирає USDC
- [ ] Спліт 5/5/90 (Foundation / validators / providers)

Деталі — у `docs/internal/TOKENOMICS_IMPLEMENTATION_PLAN.md`.

---

## Що робити цього тижня

1. **PraisonAI** — написати адаптер, відкрити PR.
2. Паралельно **Swarms** — пам'ять/векторні класи.
3. Токеноміку **не чіпати** — вона не блокує.

---

## Чек-ліст готовності до Фази 1

- [ ] 3+ злитих PR
- [ ] Хоча б 1 реальний користувач поза тобою
- [ ] SDK стабільний (без щоденних breaking changes)

---

# ДЕТАЛЬНА ЧАСТИНА

## 1. Стратегія та обґрунтування

### Чому інтеграції перші, а токеноміка потім

Feedo — інфраструктурний проєкт (децентралізоване сховище + семантичний пошук + DID). Інфраструктура має цінність лише тоді, коли нею користуються. Інтеграція в існуючі AI-фреймворки — найдешевший шлях до перших користувачів: ти приходиш у готову екосистему з розробниками і стаєш їхнім бекендом пам'яті/пошуку.

Токеноміка без користувачів = економіка порожньої мережі. Ніхто не платить → ніхто не заробляє → нодам нема сенсу підключатися. Тому порядок жорсткий: **спершу попит (інтеграції), потім економіка (токеноміка)**.

### Чому одразу PR, а не issues

- Issue — це «інтегруйте нас, будь ласка» → обговорення місяцями.
- PR — це готовий код, який лишається тільки змерджити → дні.
- Для малих проєктів (Рівень 1) мердж готового PR — питання рев'ю, а не перемовин.
- Готовий PR демонструє якість і знімає з мейнтейнера роботу.

### Правило мінімальної цінності

Кожен адаптер = «один клас, один файл, нуль залежностей». Якщо доводиться міняти кор проєкту — це вже не Рівень 1, а Рівень 2 (окремий пакет/плагін, який ядро не може відхилити).

## 2. Інвентар: що вже готово / що бракує

| Компонент | Статус | Коментар |
|---|---|---|
| DID = гаманець (`did:feedo:0x…`) | ✅ готово | `consensus-node/did.rs` |
| Реєстрація DID (personal_sign) | ✅ готово | `POST /did/register`, 500k кредитів |
| Usage key + делегація | ✅ готово | `POST /did/delegate`, `GET /did/:addr/delegation` |
| SDK Python `feedo-sdk` | ✅ 0.1.19 | PyPI |
| SDK TypeScript `feedo-protocol-sdk` | ✅ 0.1.19 | npm |
| CLI (`init`, `usage-key`, `delegate`, `deploy`, `balance`) | ✅ готово | `sdk/cli` |
| Storage (upload/download, E2EE, erasure coding) | ✅ готово | `storage-node` |
| Search (semantic, index, federated) | ✅ готово | `search-node` |
| Ledger + 500k кредитів + balance | ✅ готово | `consensus-node` |
| Сайт айдентики (EIP-6963 мульти-гаманець) | ✅ готово | `website/identity.html` |
| Метринг (списання кредитів за операції) | ⏳ частково | ledger є, enforcement нема |
| Топ-ап через контракт (USDC) | ⏳ нема | `PporTreasury.sol` (концепт) |
| Cash-out для операторів | ⏳ нема | не реалізовано |
| Rate limit за репутацією | ⏳ нема | тіри спроєктовані |

## 3. Фаза 0 — інтеграції (детально)

**Мета:** 3–5 злитих PR за 2–3 тижні. Доказ, що Feedo працює як memory/vector/RAG-бекенд.

**Загальний рецепт адаптера (для будь-якого проєкту):**
1. Форкнути репо, знайти точку розширення (memory / vectorstore / storage).
2. Скопіювати найближчий сусідній адаптер і замінити виклики на Feedo SDK.
3. Підключити DID: юзер реєструє гаманець (або дефолт-безкоштовний режим).
4. Відкрити PR з описом «Feedo — decentralized memory/vector backend».

### Рівень 1 — бліц-вхід (впорядковано за анонс-активністю)

> Порядок визначено за тим, хто реально анонсує нові інтеграції своїй ком'юніті. Пріоритет: високий анонс → швидкий мердж.

**1. PraisonAI** (`MervinPraison/PraisonAI`, Python) — ПРІОРИТЕТ №1.
- 8.9k⭐. Mervin Praison — відомий AI-ютубер: 22 відео-туторіали, X, LinkedIn, Discussions.
- Точка входу: агентна пам'ять — уже є «Mem0 Integration» та `db` для memory, ти природно вписуєшся.
- Інтерфейс: `add()`, `search()`, `get_all()` (типовий memory-контракт).
- Зусилля: 1–2 дні.

**2. Swarms** (`kyegomez/swarms`, Python) — піднято (високий анонс).
- 7.1k⭐. Kye Gomez активний: Discord, Twitter `@swarms_corp`, LinkedIn, YouTube, Blog (Medium), Events.
- Точка входу: пам'ять/векторні бази як незалежні класи.
- Зусилля: 1–2 дні.

**3. BeeAI Framework** (`i-am-bee/beeai-framework`, Python/TS) — піднято (changelog + IBM).
- 3.4k⭐. IBM / Linux Foundation. У README є «Latest updates» — таблиця з датами (вони пишуть про апдейти).
- Точка входу: ізольований шар Storage/Memory. Feedo = memory provider.
- Зусилля: 1–2 дні.

**4. DocsGPT** (`arc53/DocsGPT`, Python) — знижено (більше enterprise, ніж соц-анонс).
- 18.2k⭐. Enterprise-орієнтований, є «Lighthouse Program», але менше публічних анонсів.
- Точка входу: `/extensions/vectorstore/` — скопіювати сусідній адаптер.
- Інтерфейс: `add_texts`, `search`, `delete`.
- Зусилля: 1 день.

**5. Heurist Agent Framework** (`heurist-network/...`, TS/Python) — не перевірено.
- Нативний Web3 AI-фреймворк. Авторизація через криптогаманці — наш основний юзкейс.
- Зусилля: 2 дні.

**6. Smart Agent Tools** (`MorpheusAIs/Smart-Agent-Tools`, Python/JS) — не перевірено.
- Децентралізовані смарт-агенти. Tool для пам'яті/пошуку.
- Зусилля: 1–2 дні.

**7. Agent Memory** (`xiaona-ai/agent-memory`, Python) — знижено (0⭐, нульова анонс-цінність).
- Робити лише якщо є вільні 2 години — інтеграція тривіальна, але ком'юніті нуль.
- Зусилля: 1 день.

**~~Daydreams~~ — ПРОПУСТИТИ.** ⚠️ Півот: у README прямо «agent framework is no longer the core focus, features are obsolete». Перейшли в «Agentic Commerce».

**~~Superagent~~ — ПРОПУСТИТИ.** ⚠️ Півот: тепер це AI-safety SDK (guardrails / prompt injection), а не агент-фреймворк. Точки входу «memory backend» більше немає.

### Рівень 2 — плагіни та маркетплейси (нульовий ризик відмови ядра)

**10. ElizaOS** (`elizaos/eliza`, TypeScript).
- Окремий npm-пакет `@elizaos/plugin-feedo` (memory/database adapter).
- Твій код живе окремим пакетом — мейнтейнери ядра його не відхилять.

**11. LobeChat** (`lobehub/lobe-chat`, TypeScript).
- Публікація плагіна в їхній відкритий маркетплейс (децентралізований пошук/пам'ять).

**12. Open WebUI** (`open-webui/pipelines`, Python).
- Pipeline/Function для векторного пошуку, який юзери встановлюють за URL.

**13. AutoGPT Blocks** (`Significant-Gravitas/AutoGPT`, Python).
- Окремий reusable block для взаємодії з Feedo-сховищем.

**14. Continue** (`continuedev/continue`, TS/Python).
- Модуль індексації та кодової пам'яті для IDE.

**15. Codebuddy** (`olasunkanmi-SE/codebuddy`, TypeScript).
- AI-інженер для коду з підтримкою VectorStore.

**16. LlamaHub** (`run-llama/llama-hub`, Python).
- Окремий конектор/векторний стор для LlamaIndex (приймають майже все, якщо тести проходять).

### Рівень 3 — RAG та document-QA (середня складність)

Тут треба більше методів: фільтрація метаданих, батчі, видалення, list.

**17. R2R** (`SciPhi-AI/R2R`, Python) — модульний RAG-рушій з фабричними класами БД. Feedo = DB provider.
**18. Kotaemon** (`Cinnamon/kotaemon`, Python) — мультимодальний RAG (текст + фото, ідеально під нашу мережу).
**19. Khoj** (`khoj-ai/khoj`, Python/TS) — приватний асистент (наша E2EE з шифруванням — ідеальний метч).
**20. RAGFlow** (`infiniflow/ragflow`, Python) — document QA з відкритими абстракціями сховищ.
**21. Quivr** (`StanGirard/quivr`, Python/TS) — модуль мозку/сховища знань.
**22. AnythingLLM** (`mintplex-labs/anything-llm`, Node.js) — конектор для колекцій (план уже є: `docs/internal/FEEDO_ANYTHINGLLM_IMPLEMENTATION_PLAN.md`).
**23. CAMEL** (`camel-ai/camel`, Python) — мультиагентні RAG-системи.
**24. Lagent** (`internlm/lagent`, Python) — легкий RAG/Agent тулкіт.
**25. Cohere Toolkit** (`cohere-ai/cohere-toolkit`, Python) — модульний шаблон RAG.

### Рівень 4 — великі ком'юніті-хаби (остання черга)

Найдовше рев'ю, але максимальне покриття. Робити, коли вже є 5–10 злитих адаптерів (соцдоказ).

**26. LangChain Community** (`langchain-ai/langchain-community`, Python) — `your_vector_store.py` у `vectorstores/`.
**27. LangChain JS Community** (`langchain-ai/langchainjs`, TypeScript) — аналог у TS.
**28. Thirdweb AI Engine** (`thirdweb-dev/...`, TypeScript) — інструменти для Web3-розробників.
**29. Bittensor Subnet SDK** (`bittensor/...`, Python) — сабнет пам'яті/векторів.
**30. TencentDB Agent Memory** (TS/Python) — шар пам'яті для агентних стеків.

## 4. Фаза 1 — софт-метринг (детально)

**Критерій входу:** 3+ злитих PR, перші реальні користувачі, SDK стабільний.

**Мета:** рахувати використання, але без грошей. Проміжний крок, який готує мережу до Фази 2.

**Кроки (по файлах):**
1. `search-node/auth.py` — після DID-перевірки додати баланс-чек: `GET /did/{did}/balance` ≥ вартість операції (консенсус-виклик уже є).
2. `search-node/main.py` — визначити `operation_cost`: `/query` = 1 кредит, `/index_document` = 1 кредит/вектор, `/index_image` = 2 кредити.
3. `storage-node` — тариф за обсяг: 40 кредитів/ГБ/міс.
4. `consensus-node` — атрибуція: нода записує ledger-подію (хто, скільки, які ноди працювали). Спліт ingress/storage ~80/20.
5. `consensus-node` — репутація DID: вік + баланс + чиста історія → тіри.

> **Баланс кредитів** — перевірка через **DHT-lookup** (як DID-документ і делегація), а не через PBFT-реплікацію леджера. Так будь-яка нода зможе перевірити баланс юзера, навіть якщо кредит нарахований на іншій ноді.

**Тіри rate limit (чернетка):**
- Fresh — 10 req/s (новий DID)
- Active — 50 req/s (7+ днів, чиста історія)
- Verified — 500 req/s (депозит або ліцензія ноди)
- Enterprise — 1000+ req/s (великий комітмент + явна угода)

**Вихід із Фази 1:** метринг працює, кредити списуються, зловживання обмежує репутація. Грошей ще нема.

## 5. Фаза 2 — повна токеноміка (детально)

**Критерій входу:** реальний обсяг запитів, потреба залучати ноди-операторів (твої власні ноди вже не тягнуть).

**Оплата:**
- USDC на Polygon (нативний, не USDC.e).
- DID = гаманець → топ-ап без memo: `deposit(amount)`, `msg.sender = DID`.
- `eth_bridge.rs` моніторить `CreditClaimed(sender, amount)` → `balance[did] += amount`.

**Прайс-лист (з `docs/internal/TOKENOMICS_IMPLEMENTATION_PLAN.md`):**
| Операція | Ціна |
|---|---|
| Пошук (text-in) | $5 / 10k запитів |
| Векторизація тексту | $5 / 10k векторів |
| Векторизація зображень (CLIP) | $5 / 5k векторів |
| Зберігання | $20 / TB / міс |
| Домен `.feedo` | $5/рік або $100 назавжди |

Прив'язка: 1 запит = 1 кредит = $0.0005.

**Розподіл доходу:**
- 90% — провайдери (ноди, що виконали роботу: storage + search), спліт ingress/storage ~80/20.
- 5% — consensus validators (Top-21).
- 5% — Foundation.

**Cash-out:**
- Консенсус періодично генерує proof балансу ноди.
- Оператор забирає USDC через `PporTreasury.sol`.

**Порядок реалізації:**
1. `PporTreasury.sol` — `deposit(amount)` + cash-out.
2. `eth_bridge.rs` — моніторинг `CreditClaimed`.
3. Метринг + дедакт на search-node і storage-node (з Фази 1).
4. Атрибуція + proof балансу.
5. E2E тест: «юзер → upload → пошук → оператори отримали баланс».

## 6. Ризики та пастки

1. **Централізація через «мої ключі»** (вже пройдено): давати всім свій Pinata/Alchemy ключ = централізація особистості. Рішення: кожен юзер має свій DID + сам фандить.
2. **Sybil-стійкість репутації**: DID безкоштовні → ферма акаунтів. Рішення: вік + гроші + історія.
3. **Метринг без оплати** (Фаза 1) може виглядати як «порожній облік» — але це потрібний фундамент для Фази 2.
4. **Розпорошення**: 30 проєктів — не робити паралельно. Строго по черзі, 1–2 активних адаптери одночасно.

## 7. Definition of Done

**Фаза 0 завершена, коли:**
- [ ] PraisonAI PR злито — (PR #4032 відкрито ✅, рев'ю Approve; ⏳ чекає мерджу)
- [ ] Swarms PR злито
- [ ] BeeAI PR злито
- [ ] 1 плагін Рівня 2 опубліковано (ElizaOS або LobeChat)
- [ ] Хоча б 1 зовнішній користувач реально прогнав запит

**Фаза 1:** метринг + rate limits працюють на тестнеті.
**Фаза 2:** топ-ап + cash-out працюють на Polygon (testnet → mainnet).

## 8. Спринти

**Спринт 1 (тиждень 1):**
- PraisonAI адаптер + PR.
- Swarms адаптер (паралельно).

**Спринт 2 (тиждень 2):**
- BeeAI адаптер + PR.
- Мердж-фікси по рев'ю PraisonAI/Swarms.

**Спринт 3 (тиждень 3):**
- Плагін ElizaOS або LobeChat.
- Якщо 3+ PR злито → старт Фази 1 (метринг).

**Далі:** Фаза 1 → спостереження за реальним використанням → Фаза 2 при реальному трафіку.

---

## 9. Як діяти: PR та після мерджу (покроково)

### 9.1 Що писати в PR (Рівень 1)

**Правила PR-гігієни:**
- Один файл, один клас — не роздувати.
- Повторити їхній код-стайл і структуру (скопіювати сусідній адаптер).
- Проставити їхній PR-чек-лист, якщо є шаблон.
- CI має проходити з першого разу (прогнати локально перед пушем).

**Шаблон опису PR:**

```markdown
## What

Adds Feedo as a {memory/vector} backend.

[Feedo](https://feedo.ink) is a decentralized storage + semantic search
network. Your identity is your crypto wallet (`did:feedo:0x…`) — no
accounts, no KYC.

## Why it matters for your users

- **Decentralized memory** — data lives on a P2P network, not one cloud.
- **E2E-encrypted** (AES-256-GCM + ECIES) for private memory.
- **Free on testnet** — 500,000 credits on DID registration.

## Changes

- Added `feedo.py` (single file, class `FeedoMemory`).
- Implements the standard {memory/vectorstore} interface:
  `add()`, `search()`, `delete()`.

## How to test

1. `pip install feedo-sdk`
2. Register a DID: `feedo init`
3. `python examples/feedo_memory.py`

## Checklist

- [ ] Matches existing code style
- [ ] Tests pass
- [ ] Added entry to docs/integrations list
```

**Що просити (не забути — це головне):**
1. **Додати в їхню документацію** (розділ «integrations» / «vector stores»). Без цього тебе ніхто не знайде.
2. Лінк на свій репо + сайт.
3. (Опційно) згадку в release notes / changelog.
4. **Якщо проєкт сам пише про нові фічі** (release notes, блог, соцмережі) — прямо попроси анонс. Feedo це справді цікава фіча (децентралізована пам'ять для AI-агентів), тож для них це теж вигідний контент. Правило: за замовчуванням анонс твій, але якщо проєкт активно пише про інтеграції — проси анонс у них, це win-win.

### 9.2 Що робити ПІСЛЯ мерджу (покроково)

**Крок 1 — оновити свій README.**
Додай секцію «Used by / Integrated with» з назвою/лого проєкту. Це твій соцдоказ.

**Крок 2 — написати анонс (ти сам, не вони).**

Шаблон поста:

```text
Feedo now powers {memory / vector search} in {Project}.

Feedo is a decentralized memory layer for AI agents:
- your identity is your wallet — no accounts, no KYC
- data is E2E-encrypted on a P2P network
- free on testnet (500k credits)

Try it: {link to their integration}
Repo: github.com/Ashixi/feedo
```

**Крок 3 — куди це кидати (в порядку пріоритету):**

1. **X/Twitter** — тегнути проєкт і мейнтейнера. Малі проєкти часто ретвітять (це безкоштовний контент, який робить їх кращими).
2. **Reddit** — r/LocalLLaMA, r/selfhosted, r/ethereum, r/artificial, r/MachineLearning. Пиши як розповідь, не як рекламу (що зробив → навіщо → як спробувати).
3. **Hacker News (Show HN)** — тільки коли вже є 3+ інтеграції і живий демо. Поодинокий PR на HN виглядає як спам.
4. **Discord/Telegram спільноти** цих проєктів — закинути в канал «integrations/showcase», якщо є.

**Крок 4 — не зупинятися.** Один мердж = тиша. Робиш наступний PR. Кумулятивний ефект спрацьовує на 3–5 інтеграціях.

**Чого НЕ робити:**
- Не спамити один і той самий пост у 10 місць.
- Не йти в HN/Reddit, поки немає хоча б 1 живого користувача і демо.
- Не чекати анонсу мовчки: за замовчуванням анонс твій. Але якщо проєкт сам пише про нові фічі — явно попроси анонс (п. 9.1), це win-win.

---

## 10. Повний список проєктів (усі 30)

### Рівень 1 — бліц-вхід (за анонс-активністю)
1. **PraisonAI** — `MervinPraison/PraisonAI` — Python — 🔥 високий анонс — ✅ PR #4032, ⏳ не змерджено
2. **Swarms** — `kyegomez/swarms` — Python — 🔥 високий анонс — ✅ PR створено
3. **BeeAI Framework** — `i-am-bee/beeai-framework` — Python/TS — 🟡 changelog
4. **DocsGPT** — `arc53/DocsGPT` — Python — 🟡 enterprise
5. **Heurist Agent Framework** — `heurist-network/...` — TS/Python — не перевірено
6. **Smart Agent Tools** — `MorpheusAIs/Smart-Agent-Tools` — Python/JS — не перевірено
7. **Agent Memory** — `xiaona-ai/agent-memory` — Python — опційно
8. ~~**Daydreams**~~ — `daydreamsai/daydreams` — TypeScript — півот, пропустити
9. ~~**Superagent**~~ — `superagent-ai/superagent` — TypeScript — півот, пропустити

### Рівень 2 — плагіни та маркетплейси
10. **ElizaOS** — `elizaos/eliza` — TypeScript
11. **LobeChat** — `lobehub/lobe-chat` — TypeScript
12. **Open WebUI** — `open-webui/pipelines` — Python
13. **AutoGPT Blocks** — `Significant-Gravitas/AutoGPT` — Python
14. **Continue** — `continuedev/continue` — TS/Python
15. **Codebuddy** — `olasunkanmi-SE/codebuddy` — TypeScript
16. **LlamaHub** — `run-llama/llama-hub` — Python

### Рівень 3 — RAG та document-QA
17. **R2R** — `SciPhi-AI/R2R` — Python
18. **Kotaemon** — `Cinnamon/kotaemon` — Python
19. **Khoj** — `khoj-ai/khoj` — Python/TS
20. **RAGFlow** — `infiniflow/ragflow` — Python
21. **Quivr** — `StanGirard/quivr` — Python/TS
22. **AnythingLLM** — `mintplex-labs/anything-llm` — Node.js
23. **CAMEL** — `camel-ai/camel` — Python
24. **Lagent** — `internlm/lagent` — Python
25. **Cohere Toolkit** — `cohere-ai/cohere-toolkit` — Python

### Рівень 4 — ком'юніті-хаби
26. **LangChain Community** — `langchain-ai/langchain-community` — Python
27. **LangChain JS Community** — `langchain-ai/langchainjs` — TypeScript
28. **Thirdweb AI Engine** — `thirdweb-dev/...` — TypeScript
29. **Bittensor Subnet SDK** — `bittensor/...` — Python
30. **TencentDB Agent Memory** — TS/Python

---

## 11. PraisonAI інтеграція — PR виконано ✅ · інтеграція не підтверджена ⏳

**SDK (`feedo-sdk`):** новий клас `FeedoMemory` (`sdk/python/feedo/memory.py`) — синхронна memory-абстракція поверх search-модуля:
- авторезолв `did` з `usage_key` (через `GET /did/{0xD}/delegation`)
- `add_short` / `add_long` / `search_short` / `search_long` / `get_all` / `clear_*`
- `private=True` (дефолт) → `index_private_document`; `private=False` → `index_document`
- namespace-ізоляція: `feedo-memory:{user_id|DID}:{short|long}`

**PraisonAI:** `FeedoMemoryAdapter` (`memory/adapters/feedo_adapter.py`) + фабрика `create_feedo_memory_adapter` + реєстрація `register_memory_factory("feedo", ...)` + приклад `examples/python/feedo_memory_example.py`.

**Конфіг (мінімальний):**
```python
memory = {"provider": "feedo", "config": {"usage_key": "0x..."}}
```

**Статус:**
- ✅ PR відкрито — [MervinPraison/PraisonAI#4032](https://github.com/MervinPraison/PraisonAI/pull/4032)
- ✅ Код у гілці `feat/feedo-memory-adapter` (фікс nested-config — коміт `9bc9e426e`)
- ✅ Фінальне архітектурне рев'ю (Claude triage) — **Approve**, блокерів немає
- ⏳ Інтеграція **не підтверджена**: PR ще не змерджено мейнтейнером (12 CI-workflows чекають апруву)

---

## 12. Swarms інтеграція — PR виконано ✅ · чекає мерджу ⏳

**SDK (`feedo-sdk`):** оновлено `FeedoMemory` (версія `0.1.22`), додано універсальні методи `add`, `search`, `update`, `delete` для сумісності з сучасними фреймворками.

**Swarms:** 
- Реалізовано через концепцію **Agent Tools** (замість застарілого `swarms-memory`).
- `FeedoMemoryTools` (`examples/tools/feedo/feedo_tools.py`) експортує інструменти керування пам'яттю безпосередньо агенту.
- Додано `examples/tools/feedo/feedo_memory_example.py` та інструкції з ініціалізації.
- Додано Feedo Protocol у таблицю інтеграцій `README.md`.
- Написано юніт-тести з `MagicMock` (`tests/tools/test_feedo_tools.py`).

**Статус:**
- ✅ PR створено.
- ⏳ Чекає на рев'ю та мердж.
