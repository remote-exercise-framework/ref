FROM node:22-alpine

WORKDIR /spa-frontend

# Copy manifest first for layer caching. package-lock.json is generated on
# first `npm install`; if it is missing we fall back to `npm install` so a
# fresh checkout still boots cleanly.
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# Copy source. In dev the host bind-mount shadows everything under
# /spa-frontend except for node_modules (protected by an anonymous volume
# in compose), so host edits are reflected immediately.
COPY . .

EXPOSE 5173

ENTRYPOINT ["./entrypoint.sh"]
