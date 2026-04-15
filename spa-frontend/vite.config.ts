import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import vuetify from 'vite-plugin-vuetify';
import { fileURLToPath, URL } from 'node:url';

// The SPA is served under /spa/ and fronted by the Caddy frontend-proxy
// container on host port 8000. In dev (HOT_RELOADING=true), Caddy
// reverse-proxies /spa/* (and the /spa/@vite/client HMR websocket) to
// this container's port 5173. In prod the built bundle is baked into the
// frontend-proxy image and served directly by Caddy, so this file only
// needs the dev-mode server block.
export default defineConfig({
  base: '/spa/',
  plugins: [vue(), vuetify({ autoImport: true })],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
  },
});
