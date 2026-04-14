// Palette source of truth for the two SPA themes.
//
// Every color here becomes a Vuetify `--v-theme-*` CSS custom property once
// the theme is active, so `theme.css` can read both the Vuetify-required
// keys (primary, surface, …) and the extra scoreboard-specific tokens
// (hot-glow, rank-gold, grid-line) from one namespace.

import type { ThemeDefinition } from 'vuetify';

export const hackerDark: ThemeDefinition = {
  dark: true,
  colors: {
    // --- Vuetify-required keys --------------------------------------------
    background: '#0b0e14',
    surface: '#141922',
    'surface-variant': '#0f141d',
    primary: '#e4ff4c', // sb-hot
    secondary: '#4ec9ff', // sb-cool
    error: '#ff4757', // sb-live
    warning: '#d4a574', // sb-rank-bronze
    info: '#4ec9ff',
    success: '#7ee787',
    'on-background': '#d8dee9',
    'on-surface': '#d8dee9',
    'on-surface-variant': '#d8dee9',
    'on-primary': '#0b0e14',
    'on-secondary': '#0b0e14',
    'on-error': '#0b0e14',

    // --- Scoreboard extras ------------------------------------------------
    border: '#242b3d',
    'border-soft': '#1a1e2b',
    dim: '#8b93a7',
    muted: '#6c7693',
    'hot-glow': '#e4ff4c',
    'cool-glow': '#4ec9ff',
    'rank-gold': '#e4ff4c',
    'rank-silver': '#c0c9e0',
    'rank-bronze': '#d4a574',
    'grid-line': '#ffffff',
  },
  variables: {
    'hot-glow-alpha': '0.35',
    'cool-glow-alpha': '0.35',
    'grid-line-alpha': '0.025',
    'overlay-multiplier': '1',
  },
};

export const hackerLight: ThemeDefinition = {
  dark: false,
  colors: {
    // Warm off-white background — reads like printed terminal output.
    background: '#f4f1e8',
    surface: '#ffffff',
    'surface-variant': '#ebe6d6',
    primary: '#5b6b00', // darkened sb-hot
    secondary: '#0066a8', // darkened sb-cool
    error: '#c0392b',
    warning: '#8a5a1f',
    info: '#0066a8',
    success: '#2d7a3a',
    'on-background': '#1a1c20',
    'on-surface': '#1a1c20',
    'on-surface-variant': '#1a1c20',
    'on-primary': '#ffffff',
    'on-secondary': '#ffffff',
    'on-error': '#ffffff',

    border: '#3a3f4a',
    'border-soft': '#b8b1a0',
    dim: '#5a6173',
    muted: '#7a8295',
    'hot-glow': '#5b6b00',
    'cool-glow': '#0066a8',
    'rank-gold': '#a88600',
    'rank-silver': '#7a8295',
    'rank-bronze': '#8a5a1f',
    'grid-line': '#000000',
  },
  variables: {
    'hot-glow-alpha': '0.18',
    'cool-glow-alpha': '0.18',
    'grid-line-alpha': '0.05',
    'overlay-multiplier': '1',
  },
};
