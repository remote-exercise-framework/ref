import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent } from 'vue';
import { createPinia, setActivePinia } from 'pinia';
import { flushPromises, type VueWrapper } from '@vue/test-utils';
import App from '../../src/App.vue';
import { useAuthStore } from '../../src/stores/auth';
import { useNavStore } from '../../src/stores/nav';
import { mountBare } from '../helpers/mount';
import { setSystemPrefersLight } from '../setup';

/**
 * DefaultLayout is replaced with a pass-through: it is covered in its own
 * spec, and it pulls in Vuetify's app bar and display composables, which
 * this file has nothing to say about. Same reasoning as the chart stubs in
 * Scoreboard.spec.ts, and the same mechanism — App.vue imports it in
 * <script setup>, so vi.mock is the only thing that can intercept it.
 */
vi.mock('../../src/layouts/DefaultLayout.vue', () => ({
  default: defineComponent({
    name: 'DefaultLayout',
    template: '<div data-test="layout"><slot /></div>',
  }),
}));

const META = {
  course_name: 'OS-Security',
  registration_enabled: true,
  groups_enabled: false,
  max_group_size: 1,
  groups: [],
  password_rules: { min_length: 12, min_classes: 3 },
  mat_num_regex: '.*',
};

const AUTH = { authenticated: true, is_admin: true, is_grading_assistant: false };

function json(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

describe('App', () => {
  let wrapper: VueWrapper | undefined;

  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    document.body.className = '';
    document.title = '';
  });

  afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
  });

  /** Answer each endpoint by path, defaulting to a 404. */
  function mockApi(byPath: Record<string, ReturnType<typeof json>>) {
    const fetchMock = vi.fn((url: string) => {
      const match = Object.keys(byPath).find((p) => String(url).includes(p));
      return Promise.resolve(match ? byPath[match] : json(404, { error: 'not found' }));
    });
    globalThis.fetch = fetchMock as never;
    return fetchMock;
  }

  function allOk() {
    return mockApi({
      '/api/v2/auth/me': json(200, AUTH),
      '/api/v2/registration': json(200, META),
      '/api/scoreboard/config': json(200, { course_name: 'X', assignments: {} }),
    });
  }

  async function mountApp() {
    // RouterView has nowhere to route in this file; the router itself is
    // covered in tests/unit/router.
    wrapper = mountBare(App, { stubs: { RouterView: true } });
    await flushPromises();
    await flushPromises();
    await wrapper.vm.$nextTick();
    return wrapper;
  }

  it('renders the router view inside the layout', async () => {
    allOk();

    await mountApp();

    expect(wrapper!.find('[data-test="layout"]').exists()).toBe(true);
  });

  it('hydrates both stores on mount', async () => {
    allOk();

    await mountApp();

    expect(useAuthStore().hydrated).toBe(true);
    expect(useNavStore().hydrated).toBe(true);
    expect(useAuthStore().isAdmin).toBe(true);
    expect(useNavStore().courseName).toBe('OS-Security');
  });

  it('hydrates the two stores concurrently', async () => {
    // Promise.all, not sequential awaits — the nav probe makes two
    // requests of its own and serialising them would show as a visible
    // delay before the admin button appears.
    const fetchMock = allOk();

    await mountApp();

    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls).toContain('/api/v2/auth/me');
    expect(urls).toContain('/api/v2/registration/meta');
    // The nav store's second probe goes out in the same batch.
    expect(urls).toContain('/api/scoreboard/config');
  });

  it('initialises the theme before hydrating', async () => {
    // A late theme init would flash the wrong palette; the body class is
    // what both Vuetify and the charts read.
    allOk();

    await mountApp();

    expect(document.body.classList.contains('theme-dark')).toBe(true);
  });

  it('honours a stored theme preference', async () => {
    localStorage.setItem('refTheme', 'light');
    allOk();

    await mountApp();

    expect(document.body.classList.contains('theme-light')).toBe(true);
  });

  it('follows the system preference when no choice is stored', async () => {
    setSystemPrefersLight(true);
    allOk();

    await mountApp();

    expect(document.body.classList.contains('theme-light')).toBe(true);
  });

  describe('document title', () => {
    it('is the bare product name before the course is known', async () => {
      // The store's placeholder is the string 'REF', and appending it to
      // itself would read "REF - REF".
      mockApi({});

      await mountApp();

      expect(document.title).toBe('REF');
    });

    it('names the course once hydration lands', async () => {
      allOk();

      await mountApp();

      expect(document.title).toBe('REF - OS-Security');
    });

    it('tracks a later course-name change', async () => {
      allOk();
      await mountApp();

      useNavStore().courseName = 'Renamed';
      await wrapper!.vm.$nextTick();

      expect(document.title).toBe('REF - Renamed');
    });

    it('falls back to the bare name if the course is renamed to REF', async () => {
      allOk();
      await mountApp();

      useNavStore().courseName = 'REF';
      await wrapper!.vm.$nextTick();

      expect(document.title).toBe('REF');
    });
  });

  it('still renders when every probe fails', async () => {
    // Both stores swallow their errors, so a backend that is entirely
    // down must still leave a usable shell rather than a blank page.
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('offline')) as never;

    await mountApp();

    expect(wrapper!.find('[data-test="layout"]').exists()).toBe(true);
    expect(useAuthStore().hydrated).toBe(true);
    expect(useNavStore().hydrated).toBe(true);
    expect(useAuthStore().authenticated).toBe(false);
  });
});
