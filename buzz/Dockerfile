# Stage 1: Build the React Application
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# Stage 2: Serve using Nginx
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
# Setup SPA fallback configuration & reverse proxy routes
RUN echo 'server { \
    listen 80; \
    location / { root /usr/share/nginx/html; index index.html; try_files $uri $uri/ /index.html; } \
    location = /manifest.webmanifest { root /usr/share/nginx/html; types { } default_type application/manifest+json; } \
    location /nostr { \
        proxy_pass http://nostr-relay:7777; \
        proxy_http_version 1.1; \
        proxy_set_header Upgrade $http_upgrade; \
        proxy_set_header Connection "Upgrade"; \
        proxy_set_header Host $host; \
    } \
    location /api { \
        proxy_pass http://hermes-agent:8000; \
        proxy_set_header Host $host; \
    } \
}' > /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
