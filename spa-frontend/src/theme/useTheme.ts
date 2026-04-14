// Theme composable with three user-facing states:
//
//   'auto'  – follow the OS `prefers-color-scheme` and update live when
//             it flips (e.g. macOS auto dark/light, GNOME night-light
//             schedule, Android system toggle).
//   'dark'  – force the dark hacker theme.
//   'light' – force the light paper-terminal theme.
//
// `auto` is the default for new visitors. The toolbar button cycles
// auto → light → dark → auto.

import { ref } from 'vue';
import { useTheme as useVuetifyTheme } from 'vuetify';

export type ThemeMode = 'auto' | 'dark' | 'light';

const STORAGE_KEY = 'refTheme';
const DARK = 'hackerDark';
const LIGHT = 'hackerLight';

function readStoredMode(): ThemeMode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'auto' || stored === 'dark' || stored === 'light') {
      return stored;
    }
  } catch {
    /* ignore */
  }
  return 'auto';
}

function writeStoredMode(mode: ThemeMode) {
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    /* ignore */
  }
}

function systemPrefersLight(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: light)').matches
  );
}

function resolveThemeName(mode: ThemeMode): string {
  if (mode === 'dark') return DARK;
  if (mode === 'light') return LIGHT;
  return systemPrefersLight() ? LIGHT : DARK;
}

function applyBodyClass(name: string) {
  if (typeof document === 'undefined') return;
  document.body.classList.toggle('theme-dark', name === DARK);
  document.body.classList.toggle('theme-light', name === LIGHT);
}

// Shared across every component that pulls useTheme() — a single source
// of truth for the current mode and media-query subscription.
const mode = ref<ThemeMode>(readStoredMode());
let mediaQuery: MediaQueryList | null = null;
let listenerWired = false;

export function useTheme() {
  const vt = useVuetifyTheme();

  function apply() {
    const name = resolveThemeName(mode.value);
    vt.global.name.value = name;
    applyBodyClass(name);
  }

  function setMode(next: ThemeMode, persist = true) {
    mode.value = next;
    if (persist) writeStoredMode(next);
    apply();
  }

  function cycle() {
    // auto → light → dark → auto
    if (mode.value === 'auto') setMode('light');
    else if (mode.value === 'light') setMode('dark');
    else setMode('auto');
  }

  function init() {
    mode.value = readStoredMode();
    apply();

    if (!listenerWired && typeof window !== 'undefined' && window.matchMedia) {
      mediaQuery = window.matchMedia('(prefers-color-scheme: light)');
      const onChange = () => {
        if (mode.value === 'auto') apply();
      };
      if (mediaQuery.addEventListener) {
        mediaQuery.addEventListener('change', onChange);
      } else {
        // Older Safari
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (mediaQuery as any).addListener(onChange);
      }
      listenerWired = true;
    }
  }

  return { mode, setMode, cycle, init };
}
