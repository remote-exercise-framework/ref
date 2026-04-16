import { defineStore } from 'pinia';
import { getAuthStatus } from '../api/auth';

interface State {
  authenticated: boolean;
  isAdmin: boolean;
  isGradingAssistant: boolean;
  hydrated: boolean;
}

export const useAuthStore = defineStore('auth', {
  state: (): State => ({
    authenticated: false,
    isAdmin: false,
    isGradingAssistant: false,
    hydrated: false,
  }),

  actions: {
    async hydrate() {
      try {
        const status = await getAuthStatus();
        this.authenticated = status.authenticated;
        this.isAdmin = status.is_admin;
        this.isGradingAssistant = status.is_grading_assistant;
      } catch {
        // Leave defaults — not authenticated.
      }
      this.hydrated = true;
    },
  },
});
