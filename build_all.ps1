docker build -t itsshas/feedo-backend:latest ./protocol/backend
docker build -t itsshas/feedo-p2p:latest ./protocol/p2p-node
docker build -t itsshas/feedo-nostr-bridge:latest ./protocol/ingesters/nostr-bridge
docker build -t itsshas/feedo-algo:latest ./protocol/algo-node
docker build -t itsshas/feedo-client:latest ./feedo_search_ui
