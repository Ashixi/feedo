FROM ghcr.io/cirruslabs/flutter:stable AS build

WORKDIR /app
COPY . .

# Install dependencies and build web
ARG API_URL=/api
RUN flutter pub get
RUN flutter build web --release --dart-define=API_URL=$API_URL

FROM nginx:alpine

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy flutter web build
COPY --from=build /app/build/web /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
