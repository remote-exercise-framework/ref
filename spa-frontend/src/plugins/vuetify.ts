import 'vuetify/styles';
import { createVuetify } from 'vuetify';
import { hackerDark, hackerLight } from '../theme/tokens';

export default createVuetify({
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
