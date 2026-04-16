FROM node:22-alpine AS spa-builder
WORKDIR /build
COPY spa-frontend/package.json spa-frontend/package-lock.json ./
RUN npm ci
COPY spa-frontend/ ./
RUN npm run build

FROM caddy:2.8-alpine
RUN apk add --no-cache python3 py3-jinja2
COPY --from=spa-builder /build/dist /srv/spa-dist
COPY frontend-proxy/Caddyfile.dev /etc/caddy/Caddyfile.dev
COPY frontend-proxy/Caddyfile.prod.j2 /etc/caddy/Caddyfile.prod.j2
COPY frontend-proxy/Caddyfile.routes /etc/caddy/Caddyfile.routes
COPY frontend-proxy/render_caddyfile.py /usr/local/bin/render_caddyfile.py
COPY frontend-proxy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh /usr/local/bin/render_caddyfile.py
ENTRYPOINT ["/entrypoint.sh"]
