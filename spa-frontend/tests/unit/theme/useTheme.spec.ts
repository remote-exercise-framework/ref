import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent } from 'vue';
import type { VueWrapper } from '@vue/test-utils';
import { mountInApp } from '../../helpers/mount';
import { setSystemPrefersLight, totalMediaQueryListeners } from '../../setup';

/**
 * useTheme.ts keeps `mode`, `mediaQuery` and `listenerWired` as module
 * globals, so every test imports a FRESH copy via vi.resetModules() — a
 * static import would carry the previous test's mode and its already-wired
 * media listener.
 *
 * The composable calls Vuetify's useTheme(), so it can only run inside a
 * component; a probe component exposes the returned API.
 */
type ThemeApi = {
  mode: { value: 'auto' | 'dark' | 'light' };
  setMode: (m: 'auto' | 'dark' | 'light', persist?: boolean) => void;
  cycle: () => void;
  init: () => void;
};

const STORAGE_KEY = 'refTheme';

describe('useTheme', () => {
  let wrapper: VueWrapper | undefined;

  beforeEach(() => {
    localStorage.clear();
    document.body.className = '';
  });

  afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
  });

  /** Fresh module instance mounted in a Vuetify app. */
  async function withTheme(): Promise<ThemeApi> {
    vi.resetModules();
    const { useTheme } = await import('../../../src/theme/useTheme');
    let api!: ThemeApi;
    const Probe = defineComponent({
      setup() {
        api = useTheme() as unknown as ThemeApi;
        return () => null;
      },
    });
    wrapper = mountInApp(Probe);
    return api;
  }

  function bodyTheme(): string {
    if (document.body.classList.contains('theme-light')) return 'light';
    if (document.body.classList.contains('theme-dark')) return 'dark';
    return 'none';
  }

  describe('stored mode', () => {
    it('defaults to auto with empty storage', async () => {
      const t = await withTheme();

      expect(t.mode.value).toBe('auto');
    });

    it.each(['auto', 'dark', 'light'] as const)('honours a stored %s', async (stored) => {
      localStorage.setItem(STORAGE_KEY, stored);

      const t = await withTheme();

      expect(t.mode.value).toBe(stored);
    });

    it('falls back to auto for a stored value it does not recognise', async () => {
      localStorage.setItem(STORAGE_KEY, 'chartreuse');

      const t = await withTheme();

      expect(t.mode.value).toBe('auto');
    });

    it('falls back to auto when reading storage throws', async () => {
      // Private browsing and some embedded webviews throw on access
      // rather than returning null.
      const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('denied');
      });

      const t = await withTheme();

      expect(t.mode.value).toBe('auto');
      spy.mockRestore();
    });

    it('does not throw when writing storage fails', async () => {
      const t = await withTheme();
      const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('quota');
      });

      expect(() => t.setMode('dark')).not.toThrow();
      expect(t.mode.value).toBe('dark');
      spy.mockRestore();
    });
  });

  describe('resolution and the body class', () => {
    it('applies the dark body class for mode=dark', async () => {
      const t = await withTheme();

      t.setMode('dark');

      // chartSetup.isLightTheme() reads exactly these class names, so they
      // are asserted literally rather than through a helper.
      expect(document.body.classList.contains('theme-dark')).toBe(true);
      expect(document.body.classList.contains('theme-light')).toBe(false);
    });

    it('applies the light body class for mode=light', async () => {
      const t = await withTheme();

      t.setMode('light');

      expect(document.body.classList.contains('theme-light')).toBe(true);
      expect(document.body.classList.contains('theme-dark')).toBe(false);
    });

    it('follows a dark system preference in auto mode', async () => {
      const t = await withTheme();

      t.init();

      expect(bodyTheme()).toBe('dark');
    });

    it('follows a light system preference in auto mode', async () => {
      setSystemPrefersLight(true);

      const t = await withTheme();
      t.init();

      expect(bodyTheme()).toBe('light');
    });
  });

  describe('cycle', () => {
    it('steps auto to light to dark and back to auto', async () => {
      const t = await withTheme();
      expect(t.mode.value).toBe('auto');

      t.cycle();
      expect(t.mode.value).toBe('light');
      t.cycle();
      expect(t.mode.value).toBe('dark');
      t.cycle();
      expect(t.mode.value).toBe('auto');
    });

    it('persists each step under the refTheme key', async () => {
      const t = await withTheme();

      t.cycle();
      expect(localStorage.getItem(STORAGE_KEY)).toBe('light');
      t.cycle();
      expect(localStorage.getItem(STORAGE_KEY)).toBe('dark');
      t.cycle();
      expect(localStorage.getItem(STORAGE_KEY)).toBe('auto');
    });

    it('flips the body class as it goes', async () => {
      const t = await withTheme();

      t.cycle();
      expect(bodyTheme()).toBe('light');
      t.cycle();
      expect(bodyTheme()).toBe('dark');
    });

    it('can skip persistence', async () => {
      const t = await withTheme();

      t.setMode('dark', false);

      expect(t.mode.value).toBe('dark');
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    });
  });

  describe('auto mode reacts to the system preference changing', () => {
    // Worth knowing when reading these: the change listener and the value
    // come from two different objects. init() subscribes to one
    // MediaQueryList, but apply() calls window.matchMedia() again every
    // time instead of reading that list. So flipping only the subscribed
    // list fires the listener and then re-reads the old value;
    // setSystemPrefersLight() moves both, which is what a real browser
    // does.
    it('re-applies when the system preference flips to light', async () => {
      const t = await withTheme();
      t.init();
      expect(bodyTheme()).toBe('dark');

      setSystemPrefersLight(true);

      expect(bodyTheme()).toBe('light');
    });

    it('re-applies when the system preference flips back to dark', async () => {
      setSystemPrefersLight(true);
      const t = await withTheme();
      t.init();
      expect(bodyTheme()).toBe('light');

      setSystemPrefersLight(false);

      expect(bodyTheme()).toBe('dark');
    });

    it('ignores the system preference once a mode is forced', async () => {
      const t = await withTheme();
      t.init();
      t.setMode('dark');

      setSystemPrefersLight(true);

      expect(bodyTheme()).toBe('dark');
    });

    it('subscribes to the media query exactly once however often init runs', async () => {
      // `listenerWired` is a module global guarding the subscription, so
      // repeated init() calls must not stack listeners. Measured as a
      // delta because Vuetify's useDisplay() subscribes to matchMedia too
      // when the probe mounts inside <v-app>, so the absolute count is not
      // this module's to assert on.
      const t = await withTheme();
      const beforeInit = totalMediaQueryListeners();

      t.init();
      expect(totalMediaQueryListeners()).toBe(beforeInit + 1);

      t.init();
      t.init();

      expect(totalMediaQueryListeners()).toBe(beforeInit + 1);
    });
  });

  describe('module-global sharing', () => {
    it('shares one mode between two callers in the same module instance', async () => {
      vi.resetModules();
      const { useTheme } = await import('../../../src/theme/useTheme');
      let a!: ThemeApi;
      let b!: ThemeApi;
      const Probe = defineComponent({
        setup() {
          a = useTheme() as unknown as ThemeApi;
          b = useTheme() as unknown as ThemeApi;
          return () => null;
        },
      });
      wrapper = mountInApp(Probe);

      a.setMode('light');

      // The same ref object, so the second caller sees it immediately.
      expect(b.mode.value).toBe('light');
      expect(a.mode).toBe(b.mode);
    });

    it('re-reads storage after a module reset', async () => {
      const first = await withTheme();
      first.setMode('dark');
      wrapper!.unmount();
      wrapper = undefined;

      // A fresh module instance picks the persisted value back up rather
      // than inheriting the previous instance's in-memory ref.
      const second = await withTheme();

      expect(second.mode.value).toBe('dark');
    });
  });
});
