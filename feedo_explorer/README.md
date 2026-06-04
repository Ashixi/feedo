# Feedo Explorer

Feedo Explorer — це спеціалізований веб-клієнт та панель моніторингу (block-explorer) для децентралізованого протоколу Feedo. Інструмент призначений для адміністраторів нод, розробників dApps та аудиторів мережі для візуалізації стану P2P-топології, консенсусу та семантичних даних.

Проект архітектурно розділений на два ізольовані компоненти: статичний клієнт на Flutter Web (Frontend) та кешуючий шар індексації (FastAPI Backend).

## Технологічний Стек

### Клієнтська частина (Frontend)
*   **Фреймворк:** Flutter Web (Dart `>= 3.4.0`).
*   **Управління станом (State Management):** `flutter_riverpod` для реактивного оновлення UI.
*   **Маршрутизація:** `go_router` для управління навігацією на базі URL.
*   **Мережева взаємодія:** `dio` для обробки HTTP-запитів до індексатора.
*   **Криптографія:** `ed25519_edwards`, `ecdsa`, `crypto` для локальної генерації ключів та валідації підписів.

### Шар індексації (Backend Indexer)
*   **Фреймворк:** Python, `FastAPI`.
*   **База даних:** `SQLite` для швидкого локального кешування агрегованих даних.
*   **Сервер:** `Uvicorn` (ASGI-сервер).

---

## Архітектурний Дизайн

Модель взаємодії побудована за принципом Reverse Proxy з розділенням статичного контенту та динамічного API:

1.  **Frontend (Flutter Web):** Компілюється у статичний бандл (HTML/JS/CSS/WASM). Виконується виключно на стороні браузера клієнта. Відправляє REST-запити за відносним шляхом `/api/v1`.
2.  **Backend Indexer (FastAPI):** Виконує роль проміжного шару (middleware) між важким ядром Feedo Node та легким веб-клієнтом. Запускає фоновий процес, який з визначеною частотою опитує ендпоінти Feedo Node (`/node/metrics`, `/identity`, `/crdt` тощо) і зберігає агрегований стан у локальній базі даних. Це запобігає перевантаженню основної P2P-ноди під час високого трафіку на Explorer.
3.  **Nginx (Web Server):** Обробляє вхідний трафік. Роздає статичні файли Flutter-додатка і проксіює запити `/api/v1` до процесу FastAPI.

---

## Функціональні Модулі

Кодова база клієнта (директорія `lib/features/`) модульно розділена за зонами відповідальності протоколу:

*   **Network Topology (`network`, `nodes`):** Візуалізація графа підключень. Моніторинг активних P2P-з'єднань, адресації (Multiaddr), затримки мережі та загального стану здоров'я ноди (Liveness/Readiness).
*   **Consensus State (`consensus`):** Відстеження процесу підтвердження транзакцій алгоритмом PBFT. Відображення логів переходів станів (Pre-Prepare, Prepare, Commit) для аудиту відмовостійкості.
*   **Identity Registry (`identities`):** Перегляд локальної бази децентралізованих ідентифікаторів (DID), валідація публічних ключів (Ed25519) та перевірка делегованих прав доступу.
*   **Data & Semantic Explorer (`explorer`, `dashboard`):** Навігація по базових блоках контенту, аналіз дерева Меркла (Merkle Tree), перегляд поточного консистентного стану CRDT-об'єктів та виконання тестових семантичних запитів до Vector Brain (LanceDB).

---

## Інструкція з Розгортання (Development)

Для локальної розробки та тестування Frontend і Backend запускаються як окремі процеси.

### 1. Ініціалізація Backend Indexer
```bash
cd feedo_explorer/backend

# Створення та активація віртуального середовища
python3 -m venv venv
source venv/bin/activate

# Встановлення залежностей
pip install -r requirements.txt

# Запуск сервера
uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```
*   `DATABASE_URL`: Шлях до SQLite бази (за замовчуванням `sqlite:///./data/explorer.db`).
*   `NODE_API_URL`: Цільовий ендпоінт Feedo Node (за замовчуванням `http://127.0.0.1:8000/api/v1`).

### 2. Ініціалізація Frontend (Flutter Web)
```bash
cd feedo_explorer

# Завантаження залежностей
flutter pub get

# Запуск у режимі розробки з підключенням до Chrome
flutter run -d chrome
```

---

## Продакшн Розгортання (Production)

Для розгортання на сервері застосовується контейнеризація для бекенду та статичний хостинг для фронтенду.

### 1. Контейнеризація Backend Indexer
```bash
# Збірка Docker-образу (виконувати з кореня репозиторію)
docker build -t feedo-explorer-backend:latest ./feedo_explorer/backend

# Запуск через Docker Compose
docker compose -f docker-compose.explorer.prod.yml up -d
```
*Примітка:* Контейнер повинен знаходитися в одній Docker-мережі з основною нодою Feedo для локальної маршрутизації трафіку.

### 2. Компіляція Frontend
```bash
cd feedo_explorer
flutter build web --release
```
Згенеровані артефакти знаходитимуться у директорії `build/web/`. Їх необхідно перенести у директорію, яку обслуговує веб-сервер (наприклад, `/var/www/feedo-explorer`).

### 3. Конфігурація Nginx
Сконфігуруйте Nginx для роботи як Reverse Proxy:

```nginx
server {
    listen 80;
    server_name explorer.feedo.network;

    # Роздача статичних файлів Flutter
    location / {
        root /var/www/feedo-explorer;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # Проксіювання запитів до FastAPI
    location /api/v1/ {
        proxy_pass http://127.0.0.1:8001/api/v1/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```
Після налаштування веб-сервера інтерфейс Explorer буде доступний за вказаним доменним ім'ям та готовий до взаємодії з протоколом Feedo.
