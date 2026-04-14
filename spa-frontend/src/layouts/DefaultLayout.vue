<script setup lang="ts">
import { computed } from 'vue';
import { useNavStore } from '../stores/nav';
import { useTheme } from '../theme/useTheme';

const nav = useNavStore();
const theme = useTheme();

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
</script>

<template>
  <v-app>
    <v-app-bar color="background" border="b" class="term-appbar">
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
