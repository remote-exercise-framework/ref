import { createVuetify } from 'vuetify';
import * as components from 'vuetify/components';
import * as directives from 'vuetify/directives';
import { hackerDark, hackerLight } from '../../src/theme/tokens';

/**
 * A Vuetify instance for tests, mirroring src/plugins/vuetify.ts.
 *
 * Two deliberate differences from the production plugin:
 *
 *  - Components and directives are registered explicitly. Production
 *    relies on vite-plugin-vuetify's autoImport, which is a build-time
 *    transform and is not run under vitest (see vitest.config.ts).
 *  - `vuetify/styles` is not imported. `css: false` makes it a no-op and
 *    it is the slowest part of a mount.
 *
 * The `defaults` block must stay in sync with the production plugin: the
 * variants and densities there change the rendered DOM that the component
 * tests assert against, so a drift here shows up as confusing selector
 * failures rather than as a config problem.
 */
export function createTestVuetify() {
  return createVuetify({
    components,
    directives,
    theme: {
      defaultTheme: 'hackerDark',
      themes: {
        hackerDark,
        hackerLight,
      },
    },
    defaults: {
      VBtn: { rounded: 0, variant: 'outlined' },
      VCard: { rounded: 0, variant: 'outlined' },
      VTextField: { variant: 'outlined', density: 'comfortable' },
      VTextarea: { variant: 'outlined', density: 'comfortable' },
      VSelect: { variant: 'outlined', density: 'comfortable' },
      VAlert: { rounded: 0, variant: 'tonal', border: 'start' },
      VSheet: { rounded: 0 },
      VAppBar: { flat: true },
    },
  });
}
