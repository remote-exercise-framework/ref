import { mount, type VueWrapper } from '@vue/test-utils';
import { createPinia, getActivePinia, type Pinia } from 'pinia';
import { defineComponent, h, type Component } from 'vue';
import { VApp } from 'vuetify/components';
import { createTestVuetify } from './vuetify';

export type MountOpts = {
  props?: Record<string, unknown>;
  slots?: Record<string, unknown>;
  stubs?: Record<string, unknown>;
  provide?: Record<string | symbol, unknown>;
  plugins?: unknown[];
  /**
   * Pinia to install. Defaults to whatever `setActivePinia()` last set,
   * falling back to a fresh instance.
   *
   * The default matters: a mount that unconditionally created its own
   * pinia would hand the component a *different* store object from the one
   * the test seeded, so `useAuthStore().isAdmin = true` in the test would
   * have no effect on the component and the failure would look like a
   * rendering bug.
   */
  pinia?: Pinia;
};

function pluginList(options: MountOpts) {
  const pinia = options.pinia ?? (getActivePinia() as Pinia | undefined) ?? createPinia();
  return [createTestVuetify(), pinia, ...(options.plugins ?? [])];
}

/**
 * Mount a component inside a real <v-app>, attached to document.body.
 *
 * Both halves matter. <v-app> supplies the layout and theme injection that
 * useDisplay(), useTheme() and v-main read, and attaching to the body gives
 * Vuetify's overlay container a real parent — which is what lets a
 * v-select menu actually open instead of teleporting into a detached node.
 *
 * Returns the wrapper for the host, so reach the subject with
 * `findComponent(Comp)`, or query document.body directly.
 *
 * Callers MUST unmount (an afterEach is fine): because this attaches to the
 * body, leftover overlay containers and app roots accumulate across tests
 * and contaminate later DOM assertions.
 */
export function mountInApp<T extends Component>(Comp: T, options: MountOpts = {}): VueWrapper {
  const host = defineComponent({
    name: 'TestHost',
    setup(_props, { attrs }) {
      return () => h(VApp, null, { default: () => h(Comp as never, attrs) });
    },
  });

  // The options object is cast wholesale: @vue/test-utils derives its
  // option types from the component's own props, which a generic wrapper
  // cannot name without reproducing the component's type parameters.
  return mount(host, {
    attachTo: document.body,
    attrs: options.props,
    global: {
      plugins: pluginList(options),
      stubs: options.stubs,
      provide: options.provide,
    },
  } as never);
}

/**
 * Mount without the <v-app> wrapper. Roughly 3x faster, and enough for any
 * component that does not depend on Vuetify's layout or display
 * composables. Prefer it; reach for mountInApp() when a component needs an
 * overlay, useDisplay() or useTheme().
 */
export function mountBare<T extends Component>(Comp: T, options: MountOpts = {}): VueWrapper {
  return mount(Comp as never, {
    attachTo: document.body,
    props: options.props,
    slots: options.slots,
    global: {
      plugins: pluginList(options),
      stubs: options.stubs,
      provide: options.provide,
    },
  } as never);
}
