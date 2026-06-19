$ErrorActionPreference = "Stop"

Write-Host "Building feedo-nostr-node..."
docker build -f Dockerfile.nostr -t ashixi/feedo-nostr-node:latest .

Write-Host "Building feedo-paragraph-node..."
docker build -f Dockerfile.paragraph -t ashixi/feedo-paragraph-node:latest .

Write-Host "Building feedo-full-node..."
docker build -f Dockerfile.full -t ashixi/feedo-full-node:latest .

Write-Host "Pushing images to Docker Hub (ensure you are logged in)..."
docker push ashixi/feedo-nostr-node:latest
docker push ashixi/feedo-paragraph-node:latest
docker push ashixi/feedo-full-node:latest

Write-Host "All done!"
