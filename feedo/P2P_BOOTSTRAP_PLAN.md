# Feedo P2P Bootstrap + Auto-Peer Plan

Дата: 2026-05-30

## Мета

Зробити так, щоб:

1. Нова нода гарантовано знаходила вашу VPS-ноду (`api.feedo.ink` / `178.18.253.94`) при старті.
2. Після першого підключення список доступних peer-ів поповнювався автоматично.
3. Мережа могла працювати без центрального сервера (seed-нода потрібна тільки для "першого контакту").

---

## Поточний стан (коротко)

У `feedo-core` вже є:

- `libp2p` + `Kademlia` + `Gossipsub` + `mDNS`
- listen на `0.0.0.0:4001`

Обмеження зараз:

- `mDNS` працює переважно в межах LAN, не для глобального інтернет-discovery.
- bootstrap-логіка неповна: потрібен явний `dial` по multiaddr + регулярні retry.

---

## Фаза 1 (обов'язково): стабільний глобальний bootstrap

### 1) Стабільний PeerId вашої VPS-ноди

Що зробити в `feedo-core/src/main.rs`:

- Додати змінну `PEER_KEY_PATH` (наприклад `/app/db/peer_key.bin`).
- На старті:
  - якщо файл існує -> завантажити keypair;
  - якщо ні -> згенерувати keypair, зберегти у файл.

Результат: після рестарту VPS `PeerId` не змінюється, клієнти не "втрачають" seed.

### 2) Повноцінний bootstrap connect

Додати env:

- `BOOTSTRAP_NODES` (CSV multiaddr), приклад:

`/dns4/api.feedo.ink/udp/4001/quic-v1/p2p/<VPS_PEER_ID>,/ip4/178.18.253.94/udp/4001/quic-v1/p2p/<VPS_PEER_ID>`

Логіка на старті:

1. Розпарсити `BOOTSTRAP_NODES`.
2. Для кожної адреси:
   - витягти `PeerId`;
   - додати адресу в `kademlia.add_address(peer_id, addr)`;
   - виконати `swarm.dial(full_multiaddr)`.
3. Після першого успішного конекту запускати `kademlia.bootstrap()`.

### 3) Регулярний retry bootstrap

Додати `tokio::interval` (наприклад 30-60 сек):

- якщо `num_peers == 0` або нижче порога -> повторити `dial + bootstrap` по seed-адресах.

### 4) Інфраструктура VPS

- Відкрити UDP `4001` у firewall/security group (для QUIC).
- Переконатися, що DNS для `api.feedo.ink` не блокує UDP-трафік для P2P.
- Тримати `4001:4001` у Docker.

---

## Фаза 2 (ваше прохання): авто-поповнення списку peer-ів

Нижче схема, щоб список "через яку ноду підключатися" поповнювався сам.

### 1) Peer cache на диску (локальний bootstrap cache)

Додати файл кешу, наприклад:

- `/app/db/peer_cache.json`

Що зберігати на peer:

- `peer_id`
- `multiaddrs[]`
- `last_seen_unix`
- `success_count`
- `fail_count`
- `score`

Поведінка:

1. На старті завантажити кеш і пробувати підключення не тільки до `BOOTSTRAP_NODES`, а й до top-N peer-ів з кешу.
2. Після успішного конекту оновлювати `last_seen`, `success_count`, `score`.
3. На помилках збільшувати `fail_count`, знижувати `score`.
4. TTL/GC: видаляти peer-и, яких не бачили довго (наприклад 7-30 днів).

Це вже дає авто-поповнення без центрального реєстру.

### 2) Автоматичне збагачення peer cache з Identify

В обробнику `SwarmEvent::Behaviour(Identify(...))`:

- брати `listen_addrs` remote peer-а;
- додавати їх в Kademlia (`add_address`);
- зберігати в `peer_cache.json`.

Тобто кожен новий контакт автоматично розширює локальний список доступних вузлів.

### 3) Peer exchange через Gossipsub (опційно, але рекомендовано)

Додати окремий topic, наприклад `feedo_peer_announce_v1`.

Формат announce-повідомлення:

- `peer_id`
- `listen_addrs[]`
- `timestamp`
- `nonce`
- `signature`

Правила:

1. Раз на N хвилин нода публікує власний announce.
2. Отримавши announce, валідовує:
   - свіжість `timestamp`;
   - формат адрес;
   - підпис/відповідність `peer_id`.
3. Валідні адреси додаються у `peer_cache.json` з низьким стартовим score.

Так список буде природно рости при активності мережі.

### 4) Anti-poisoning/безпека для авто-списку

Щоб список не "засмічувався":

- Ліміт нових peer-ів за інтервал (rate limit).
- Додавати в active bootstrap candidates тільки після успішного `dial`.
- Score-based відбір (підключатися спочатку до найнадійніших).
- Blacklist/banlist для явних зловмисних/битих адрес.

---

## Рекомендована модель discovery (без центрального сервера)

1. **Початковий контакт**: `BOOTSTRAP_NODES` (ваша VPS).
2. **Після контакту**: Kademlia + Identify дають більше peer-ів.
3. **Накопичення знань**: локальний `peer_cache.json` з TTL/score.
4. **Поширення знань**: optional peer announce topic.

Після цього seed-нода не є центральним сервером для всіх операцій, а тільки стартовою точкою входу.

---

## Мінімальний backlog по коду

### P0 (зробити першим)

1. Persist keypair (`PEER_KEY_PATH`) для стабільного PeerId.
2. `BOOTSTRAP_NODES` + явний `dial` + `kademlia.add_address`.
3. Періодичний bootstrap retry.
4. Логування: кого пробуємо, успіх/помилка, поточний `num_peers`.

### P1

1. `peer_cache.json` (load/save, TTL, score).
2. Поповнення кешу з Identify events.
3. Стартові підключення: seed + top peers з кешу.

### P2

1. Gossipsub peer announce topic.
2. Валідація анонсів + rate limits + anti-poisoning.

---

## Env-конфіг приклад (клієнтська нода)

```env
BOOTSTRAP_NODES=/dns4/api.feedo.ink/udp/4001/quic-v1/p2p/<VPS_PEER_ID>,/ip4/178.18.253.94/udp/4001/quic-v1/p2p/<VPS_PEER_ID>
PEER_KEY_PATH=/app/db/peer_key.bin
PEER_CACHE_PATH=/app/db/peer_cache.json
BOOTSTRAP_RETRY_SECS=45
MIN_PEERS_BEFORE_RETRY=2
```

---

## Критерії готовності (DoD)

1. Нова нода з чистим кешем підключається до VPS через `BOOTSTRAP_NODES`.
2. Через 1-2 хвилини має більше ніж 1 peer у мережі (де доступно).
3. Після рестарту нова нода може знайти мережу навіть якщо один seed тимчасово недоступний (за рахунок `peer_cache.json`).
4. Пости/контент між двома нодами проходять в обидва боки (gossipsub + DHT fetch).
