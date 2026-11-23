import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createPinia, setActivePinia } from 'pinia';
import { mount, type VueWrapper } from '@vue/test-utils';
import { createRouter, createMemoryHistory } from 'vue-router';
import DefaultLayout from '../../src/layouts/DefaultLayout.vue';
import { useNavStore } from '../../src/stores/nav';
import { createTestVuetify } from '../helpers/vuetify';
import { setViewportWidth } from '../setup';

const Blank = defineComponent({ render: () => h('div') });

function makeRouter() {
  // v-btn with `to` renders a router-link, so the layout needs a router
  // even though no test navigates.
  return createRouter({
    history: createMemoryHistory('/spa/'),
    routes: [
      { path: '/', redirect: '/register' },
      { path: '/register', component: Blank },
      { path: '/restore-key', component: Blank },
      { path: '/scoreboard', component: Blank },
    ],
  });
}

describe('DefaultLayout', () => {
  let wrapper: VueWrapper | undefined;

  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    document.body.className = '';
  });

  afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
  });

  async function mountLayout(slot = '<p data-test="page">page body</p>') {
    const router = makeRouter();
    await router.push('/register');
    await router.isReady();
    wrapper = mount(DefaultLayout, {
      global: { plugins: [createTestVuetify(), router] },
      slots: { default: slot },
      attachTo: document.body,
    } as never);
    await wrapper.vm.$nextTick();
    return wrapper;
  }

  it('renders its slot inside the main content frame', async () => {
    await mountLayout();

    expect(wrapper!.find('.term-content [data-test="page"]').text()).toBe('page body');
  });

  it('shows the course name from the nav store', async () => {
    await mountLayout();

    // The placeholder, since nothing hydrated the store.
    expect(wrapper!.find('.term-appbar-title').text()).toContain('REF');
  });

  it('picks up a hydrated course name', async () => {
    await mountLayout();
    useNavStore().courseName = 'OS-Security';
    await wrapper!.vm.$nextTick();

    expect(wrapper!.find('.term-appbar-title').text()).toContain('OS-Security');
  });

  it('renders a nav button per visible item and skips hidden ones', async () => {
    await mountLayout();

    const tabs = wrapper!.findAll('.term-nav-center .term-tab');

    // The scoreboard item starts hidden.
    expect(tabs.map((t) => t.text())).toEqual(['REGISTER', 'RESTORE KEY']);
  });

  it('adds a nav button when the store reveals one', async () => {
    await mountLayout();
    const nav = useNavStore();

    const sb = nav.navItems.find((i) => i.to === '/scoreboard');
    sb!.show = true;
    await wrapper!.vm.$nextTick();

    expect(wrapper!.findAll('.term-nav-center .term-tab').map((t) => t.text())).toContain(
      'SCOREBOARD',
    );
  });

  it('links the admin button straight at the Flask app, not a route', async () => {
    // /admin is server-rendered Jinja, so this has to leave the SPA — a
    // router-link would resolve to nothing and swallow the click.
    await mountLayout();

    const admin = wrapper!.find('a[href="/admin"]');

    expect(admin.exists()).toBe(true);
    // No router-link classes, i.e. vue-router is not managing it.
    expect(admin.classes().join(' ')).not.toContain('router-link');
  });

  it('routes the nav buttons through vue-router', async () => {
    await mountLayout();

    const tab = wrapper!.find('.term-nav-center .term-tab');

    expect(tab.attributes('href')).toBe('/spa/register');
  });

  describe('theme button', () => {
    function themeButton() {
      return wrapper!.findAll('button, a').find((el) => {
        const label = el.attributes('aria-label') ?? '';
        return label.startsWith('Theme:');
      })!;
    }

    it('starts in auto with the auto icon and a label naming the next step', async () => {
      await mountLayout();

      const btn = themeButton();

      expect(btn.attributes('aria-label')).toBe(
        'Theme: auto — follow system (click for light)',
      );
      expect(btn.html()).toContain('mdi-theme-light-dark');
    });

    it('cycles auto to light to dark on successive clicks', async () => {
      await mountLayout();

      await themeButton().trigger('click');
      expect(themeButton().attributes('aria-label')).toBe('Theme: light (click for dark)');
      expect(themeButton().html()).toContain('mdi-weather-sunny');

      await themeButton().trigger('click');
      expect(themeButton().attributes('aria-label')).toBe('Theme: dark (click for auto)');
      expect(themeButton().html()).toContain('mdi-weather-night');

      await themeButton().trigger('click');
      expect(themeButton().attributes('aria-label')).toContain('auto');
    });

    it('mirrors the label into the title so it is a hover tooltip too', async () => {
      await mountLayout();

      const btn = themeButton();

      expect(btn.attributes('title')).toBe(btn.attributes('aria-label'));
    });
  });

  describe('dev banner', () => {
    it('stays out of the DOM in a production build', async () => {
      // vitest runs with import.meta.env.DEV true, so production is the
      // case that has to be stubbed. A real `vite build` tree-shakes the
      // banner out of the bundle entirely.
      vi.stubEnv('DEV', false);

      await mountLayout();

      expect(wrapper!.find('.dev-banner').exists()).toBe(false);
    });

    it('warns loudly when served by vite dev', async () => {
      // `vite dev` is not a production server, and the project's rule is
      // that --hot-reloading never runs on a public host. The banner is
      // the only in-app signal of that.
      await mountLayout();

      const banner = wrapper!.find('.dev-banner');
      expect(banner.exists()).toBe(true);
      expect(banner.text()).toContain('vite dev');
      expect(banner.text()).toContain('do not expose');
      expect(banner.attributes('role')).toBe('status');
    });
  });

  describe('responsive app bar', () => {
    /**
     * The height lands on the VAppBar's prop rather than an inline style,
     * so it is read off the component instead of the DOM.
     */
    function barHeight(): number {
      return Number(wrapper!.findComponent({ name: 'VAppBar' }).props('height'));
    }

    it('stacks the nav and doubles the bar height on a narrow viewport', async () => {
      // lgAndDown covers everything below Vuetify's xl breakpoint.
      setViewportWidth(800);

      await mountLayout();

      expect(wrapper!.find('.term-appbar').classes()).toContain('term-appbar--stacked');
      expect(barHeight()).toBe(112);
    });

    it('keeps one row on a wide viewport', async () => {
      setViewportWidth(2000);

      await mountLayout();

      expect(wrapper!.find('.term-appbar').classes()).not.toContain('term-appbar--stacked');
      expect(barHeight()).toBe(64);
    });

    it('restacks when the window is resized after mount', async () => {
      setViewportWidth(2000);
      await mountLayout();
      expect(barHeight()).toBe(64);

      setViewportWidth(800);
      await wrapper!.vm.$nextTick();

      expect(barHeight()).toBe(112);
      expect(wrapper!.find('.term-appbar').classes()).toContain('term-appbar--stacked');
    });
  });
});
