variable "DOCKER_HUB_NAMESPACE" {
  default = "feedo-local"
}

variable "IMAGE_TAG" {
  default = "latest"
}

group "default" {
  targets = ["node"]
}

target "common" {
  context = "."
  dockerfile = "Dockerfile"
}

target "node" {
  inherits = ["common"]
  args = {
    RUST_CORE_URL = "http://127.0.0.1:8041/local/publish"
  }
  tags = [
    "${DOCKER_HUB_NAMESPACE}/feedo-node:${IMAGE_TAG}",
    "${DOCKER_HUB_NAMESPACE}/feedo-node:latest",
  ]
}