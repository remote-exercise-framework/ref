import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath, URL } from 'node:url';

// Deliberately NOT a merge of vite.config.ts: tests want neither the
// `base: '/spa/'` prefix nor the dev `server` block, and they must not run
// vite-plugin-vuetify. That plugin's autoImport rewrites SFC script blocks
// to pull in per-component styles, which only half-works once `css: false`
// stubs them out and fails as "Failed to resolve component: v-card" in some
// files but not others. tests/helpers/vuetify.ts registers the components
// globally instead.
//
// TZ is pinned here, at config load, because this runs before the test
// workers fork. ranking/util.ts builds Dates in local time and
// chartSetup.ts constructs Intl.DateTimeFormat instances at import time, so
// an unpinned zone turns date assertions into off-by-hours puzzles. UTC
// rather than the project's Europe/Berlin: a zone with DST makes date
// fixtures depend on which month they were written in.
process.env.TZ = 'UTC';

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    environmentOptions: {
      // A real document.body for useTheme's applyBodyClass and
      // chartSetup's isLightTheme, and a base URL so a fetch that escapes
      // its mock fails with something readable instead of "Invalid URL".
      jsdom: { url: 'http://localhost/spa/' },
    },
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.spec.ts'],
    css: false,
    env: { TZ: 'UTC' },
    server: {
      // Vuetify ships ESM that has to go through Vite's pipeline rather
      // than Node's CJS interop, or createVuetify arrives as a namespace
      // object instead of a function.
      deps: { inline: ['vuetify'] },
    },
    pool: 'threads',
    restoreMocks: true,
    clearMocks: true,
    unstubEnvs: true,
    unstubGlobals: true,
    coverage: {
      provider: 'v8',
      reportsDirectory: './coverage',
      include: ['src/**/*.{ts,vue}'],
      exclude: [
        'src/main.ts',            // app bootstrap; covered by the browser tests
        'src/plugins/vuetify.ts', // a config object
        'src/theme/tokens.ts',    // colour literals, not logic
        'src/**/*.d.ts',

        // Calls createWebHistory() at import time, which reads
        // window.history and bakes in the '/spa/' base. Importing it under
        // jsdom is not meaningful, so tests/unit/router rebuilds the same
        // route table on a memory history instead.
        'src/router/index.ts',

        // No usages anywhere in src/. Excluded rather than tested so the
        // report shows real gaps; delete them or wire them up, but do not
        // write tests to make dead code look covered.
        'src/components/PasswordHelp.vue',
        'src/components/scoreboard/HighscoreCard.vue',
      ],
      thresholds: { lines: 80, functions: 80, branches: 70 },
    },
  },
});
