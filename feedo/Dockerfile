# --- ЕТАП 1: Збірка Rust ---
FROM rustlang/rust:nightly AS rust-builder
WORKDIR /build
# Копіюємо код Rust і протоколи
COPY feedo-core/ ./feedo-core/
COPY proto/ ./proto/
WORKDIR /build/feedo-core
RUN apt-get update && apt-get install -y pkg-config libssl-dev protobuf-compiler
RUN cargo build --release
RUN strip target/release/feedo-core
# --- ЕТАП 2: Фінальний образ (Python + Rust) ---
FROM python:3.11-slim
WORKDIR /app

ARG RUST_CORE_URL=http://127.0.0.1:8041/local/publish

# Встановлюємо системні залежності для Python-бібліотек і для роботи Rust-бінарника
RUN apt-get update && apt-get install -y gcc libssl-dev ca-certificates bash protobuf-compiler && rm -rf /var/lib/apt/lists/*

# Копіюємо Python залежності та встановлюємо їх
# У фінальному етапі
COPY feedo-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt grpcio-tools && \
    rm -rf /root/.cache/pip

# Копіюємо весь код Python-частини
COPY feedo-api/ /app/

# Копіюємо протокольну бібліотеку, щоб вона була імпортована як `feedo_parser`
COPY feedo_parser/ /app/feedo_parser/

# Копіюємо nostr bridge (proxy)
COPY feedo_proxy/ /app/feedo_proxy/

# Копіюємо proto і генеруємо python класи
COPY proto/ /app/proto/
RUN python3 -m grpc_tools.protoc -I=/app/proto --python_out=/app /app/proto/feedo.proto

# Переносимо скомпільований Rust-бінарник з першого етапу
COPY --from=rust-builder /build/feedo-core/target/release/feedo-core /app/feedo-core

# Копіюємо наш скрипт запуску і робимо його виконуваним
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Відкриваємо порти (8040 - FastAPI, 4001 - P2P мережа)
EXPOSE 8040 4001

# Вказуємо змінну оточення, щоб Python знав, де локальний Rust (тепер це localhost всередині одного контейнера)
ENV RUST_CORE_URL=${RUST_CORE_URL}

# Запускаємо скрипт
CMD ["/app/start.sh"]