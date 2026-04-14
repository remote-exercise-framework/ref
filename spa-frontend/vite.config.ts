import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import vuetify from 'vite-plugin-vuetify';
import { fileURLToPath, URL } from 'node:url';

// The SPA is served under /v2/ both in dev (Vite dev server) and prod
// (vite preview). In dev/preview the Vite proxy forwards API + download
// URLs to the Flask `web` container at http://web:8000, so from the
// browser's perspective everything is same-origin against the
// `spa-frontend` container's port.
const BACKEND = process.env.SPA_BACKEND_URL ?? 'http://web:8000';

const proxyRules = {
  '/api':              { target: BACKEND, changeOrigin: true },
  '/student/download': { target: BACKEND, changeOrigin: true },
  '/static':           { target: BACKEND, changeOrigin: true },
};

export default defineConfig({
  base: '/v2/',
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
    proxy: proxyRules,
  },
  preview: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: proxyRules,
  },
});
