# Stage 1: Build
# Context: microservices/ (workspace root)
FROM rust:1.88-slim-bookworm AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y pkg-config libssl-dev protobuf-compiler && rm -rf /var/lib/apt/lists/*

# Copy workspace manifest and all member crates
COPY Cargo.toml Cargo.lock ./
COPY shared-proto shared-proto/
COPY consensus-node consensus-node/
COPY storage-node storage-node/

# Build only consensus-node (release, stripped)
RUN cargo build --release --bin consensus-node

# Stage 2: Runtime
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /build/target/release/consensus-node /app/consensus-node

EXPOSE 3000 50051
CMD ["/app/consensus-node"]