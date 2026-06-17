# Stage 1: Build the Flutter Web App
FROM ubuntu:22.04 AS build

# Install necessary dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    unzip \
    xz-utils \
    zip \
    libglu1-mesa

# Clone Flutter from the stable channel
RUN git clone https://github.com/flutter/flutter.git -b stable /usr/local/flutter
ENV PATH="/usr/local/flutter/bin:/usr/local/flutter/bin/cache/dart-sdk/bin:${PATH}"

# Pre-download Flutter binaries
RUN flutter doctor -v

WORKDIR /app

# Copy pubspec and l10n files first to leverage Docker cache
COPY pubspec.* ./
COPY l10n.yaml ./
COPY lib/l10n ./lib/l10n
RUN flutter pub get

ARG CACHEBUST=1
# Copy the rest of the project and build
COPY . .
RUN flutter build web


