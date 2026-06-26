FROM rust:latest as builder

WORKDIR /usr/src/p2p-node
COPY . .
RUN apt-get update && apt-get install -y protobuf-compiler
RUN cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y libssl-dev ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/src/p2p-node/target/release/feedo-core /usr/local/bin/feedo-core
CMD ["feedo-core"]
