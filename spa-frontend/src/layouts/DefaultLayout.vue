<script setup lang="ts">
import { computed } from 'vue';
import { useDisplay } from 'vuetify';
import { useNavStore } from '../stores/nav';
import { useTheme } from '../theme/useTheme';

const nav = useNavStore();
const theme = useTheme();
const display = useDisplay();

// import.meta.env.DEV is true when Vite serves the app via `vite dev`
// (HMR); a production `vite build` bakes this to false. The banner is
// tree-shaken out of the prod bundle entirely.
const devMode = import.meta.env.DEV;

const themeIcon = computed(() => {
  switch (theme.mode.value) {
    case 'dark':
      return 'mdi-weather-night';
    case 'light':
      return 'mdi-weather-sunny';
    default:
      return 'mdi-theme-light-dark';
  }
});

const themeLabel = computed(() => {
  switch (theme.mode.value) {
    case 'dark':
      return 'Theme: dark (click for auto)';
    case 'light':
      return 'Theme: light (click for dark)';
    default:
      return 'Theme: auto — follow system (click for light)';
  }
});

const stackedNav = computed(() => display.lgAndDown.value);
const appBarHeight = computed(() => (stackedNav.value ? 112 : 64));
</script>

<template>
  <v-app>
    <v-system-bar
      v-if="devMode"
      class="dev-banner"
      height="26"
      role="status"
      aria-label="Development server warning"
    >
      <v-icon size="16" class="mr-2">mdi-alert</v-icon>
      <span>
        Served by <strong>vite dev</strong> with HMR &mdash; do not expose
        this instance publicly.
      </span>
    </v-system-bar>
    <v-app-bar
      color="background"
      border="b"
      :height="appBarHeight"
      :class="['term-appbar', { 'term-appbar--stacked': stackedNav }]"
    >
      <template #prepend>
        <v-app-bar-title class="term-appbar-title">
          <span class="term-hot">{{ nav.courseName }}</span>
          <span class="term-muted"> // REF</span>
        </v-app-bar-title>
      </template>
      <v-spacer />
      <v-btn
        icon
        variant="text"
        :aria-label="themeLabel"
        :title="themeLabel"
        @click="theme.cycle"
      >
        <v-icon>{{ themeIcon }}</v-icon>
      </v-btn>
      <v-btn
        icon
        variant="text"
        href="/admin"
        aria-label="Admin area (login required)"
        title="Admin area (login required)"
      >
        <v-icon>mdi-shield-account-outline</v-icon>
      </v-btn>
      <div class="term-nav-center">
        <v-btn
          v-for="item in nav.visibleItems"
          :key="item.to"
          :to="item.to"
          variant="text"
          class="term-tab"
        >
          {{ item.label }}
        </v-btn>
      </div>
    </v-app-bar>
    <v-main>
      <div class="term-frame">
        <div class="term-content">
          <slot />
        </div>
      </div>
    </v-main>
  </v-app>
</template>

<style scoped>
.dev-banner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.25rem;
  padding: 0.35rem 0.75rem;
  font-size: 0.8rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  color: #1a1a1a;
  background: repeating-linear-gradient(
    -45deg,
    #f9b000,
    #f9b000 12px,
    #1a1a1a 12px,
    #1a1a1a 24px
  );
}
.dev-banner > span {
  padding: 0.15rem 0.5rem;
  background: #f9b000;
  border-radius: 2px;
}
.dev-banner strong {
  font-weight: 800;
}
</style>
