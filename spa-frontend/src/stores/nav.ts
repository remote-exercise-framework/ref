// Single Pinia store for nav items + course name. This is the intended
// extension point for admin tabs: later code pushes items into `navItems`
// (optionally gated on an auth probe) and the layout picks them up
// without any further refactor.

import { defineStore } from 'pinia';
import { getRegistrationMeta } from '../api/registration';
import { getScoreboardConfig } from '../api/scoreboard';

export interface NavItem {
  to: string;
  label: string;
  show: boolean;
}

interface State {
  courseName: string;
  hydrated: boolean;
  navItems: NavItem[];
}

export const useNavStore = defineStore('nav', {
  state: (): State => ({
    courseName: 'REF',
    hydrated: false,
    navItems: [
      { to: '/register', label: 'REGISTER', show: true },
      { to: '/restore-key', label: 'RESTORE KEY', show: true },
      { to: '/scoreboard', label: 'SCOREBOARD', show: false },
    ],
  }),

  getters: {
    visibleItems: (s) => s.navItems.filter((i) => i.show),
  },

  actions: {
    async hydrate() {
      try {
        const meta = await getRegistrationMeta();
        this.courseName = meta.course_name;
        const register = this.navItems.find((i) => i.to === '/register');
        if (register) register.show = meta.registration_enabled;
      } catch {
        // Leave defaults — the page itself will surface a hard error.
      }
      try {
        await getScoreboardConfig();
        const sb = this.navItems.find((i) => i.to === '/scoreboard');
        if (sb) sb.show = true;
      } catch {
        // 404 means scoreboard disabled — nav item stays hidden.
      }
      this.hydrated = true;
    },
  },
});
