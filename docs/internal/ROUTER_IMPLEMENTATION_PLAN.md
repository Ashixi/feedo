# Feedo Router Node Implementation Plan

Цей документ описує архітектурний перехід від статичного `seed_nodes.json` до динамічної системи виявлення сервісів (Service Discovery) на базі нової **Router Node** (Signaling Server).

## Design Decisions

- **Технологія Router Node:** Вибрано **Python (FastAPI)** для швидкості розробки та гнучкості.
- **Автентифікація нод:** **Так, обов'язково.** При реєстрації (`/register`) та пінгу (`/heartbeat`) нода повинна відправляти свій публічний ключ та криптографічний підпис (Signature), щоб роутер міг переконатися, що це справжня нода екосистеми Feedo, а не фейкова, яка намагається спамити чи перехоплювати трафік.

---

## Proposed Changes

Ми створимо новий мікросервіс і оновимо всі існуючі компоненти.

### 1. New Microservice: Router Node (Signaling Server)

Новий легковаговий бекенд, який слугуватиме єдиною точкою входу (точкою знайомства) для мережі.

#### [NEW] `microservices/router-node/`
Створення нового мікросервісу з наступними ендпоінтами:
- `POST /register`: Нода (Search/Storage/Consensus) повідомляє про свою появу, передаючи розширений payload:
  - `type` (напр. "search")
  - `p2p_addr` (для внутрішнього зашифрованого зв'язку через libp2p)
  - `internal_http` (внутрішня IP/порт для резерву)
  - `public_domain` (опціонально, публічний HTTPS-домен для SDK/клієнтів)
- `POST /heartbeat`: Ноди відправляють пінг кожні 30 секунд, щоб підтвердити, що вони живі. Якщо пінгу немає > 60 сек, роутер видаляє ноду зі списку.
- `GET /discover?type={node_type}`: Повертає список живих нод вказаного типу (використовується SDK та іншими нодами для P2P-з'єднання).

---

### 2. Microservices (Search, Storage, Consensus)

Всі ноди повинні навчитися спілкуватися з Router Node при старті та під час роботи.

#### [MODIFY] `microservices/search-node/main.py`
- Видалити логіку парсингу `seed_nodes.json`.
- Додати фонову задачу (`asyncio.create_task`), яка при старті робить `POST /register` на `router.feedo.ink`.
- Додати цикл для відправки `POST /heartbeat` кожні 30 секунд.

#### [MODIFY] `microservices/storage-node/src/main.rs` & `microservices/consensus-node/src/main.rs`
- Замінити парсинг статичного JSON на HTTP GET запит до `router.feedo.ink/discover`, щоб отримати список P2P-адрес для лінкування (dialing).
- Додати фоновий потік (thread/tokio task), який реєструє ноду та відправляє heartbeat.

---

### 3. SDKs (Python & TypeScript)

SDK більше не матимуть жорстко зашитих масивів з доменами. Вони динамічно запитуватимуть адресу найкращої ноди.

#### [MODIFY] `sdk/python/feedo/router.py`
- Видалити хардкод масивів `search`, `consensus`, `storage`.
- У методі `_find_fastest_node()` SDK має спочатку зробити `GET https://router.feedo.ink/discover?type=search`, отримати масив живих нод, і вже між ними вимірювати пінг або брати першу-ліпшу.
- Додати кешування результатів від роутера на 5-10 хвилин, щоб не спамити роутер при кожному запиті.

#### [MODIFY] `sdk/typescript/src/router.ts`
- Аналогічні зміни для TypeScript SDK: динамічне завантаження списку нод із роутера замість статичного конфігу.

---

## Verification Plan

### Automated Tests
- Запуск локального Router Node.
- Запуск Consensus Node, перевірка чи вона з'явилася в реєстрі роутера.
- Запуск Storage Node, перевірка чи вона з'явилася в реєстрі роутера і підключилася до Consensus.
- Запуск Search Node, перевірка чи вона успішно знайшла Storage та Consensus ноди через роутер.

### Manual Verification
- Зімітувати падіння Storage Node (вбити процес).
- Перевірити, що через 60 секунд роутер видалить її зі списку живих.
- Перевірити, що Python SDK більше не намагається підключитися до "мертвої" ноди, а миттєво отримує нову адресу від роутера.
