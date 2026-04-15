FROM node:22-alpine AS spa-builder
WORKDIR /build
COPY spa-frontend/package.json spa-frontend/package-lock.json ./
RUN npm ci
COPY spa-frontend/ ./
RUN npm run build

FROM caddy:2.8-alpine
COPY --from=spa-builder /build/dist /srv/spa-dist
COPY frontend-proxy/Caddyfile.dev /etc/caddy/Caddyfile.dev
COPY frontend-proxy/Caddyfile.prod /etc/caddy/Caddyfile.prod
COPY frontend-proxy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
