import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useAuthStore } from '../../../src/stores/auth';

function mockAuth(body: unknown, status = 200) {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  }) as never;
}

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('starts unauthenticated and unhydrated', () => {
    const auth = useAuthStore();

    expect(auth.authenticated).toBe(false);
    expect(auth.isAdmin).toBe(false);
    expect(auth.isGradingAssistant).toBe(false);
    expect(auth.hydrated).toBe(false);
  });

  it('maps the snake_case API fields onto camelCase state', async () => {
    mockAuth({ authenticated: true, is_admin: true, is_grading_assistant: true });
    const auth = useAuthStore();

    await auth.hydrate();

    expect(auth.authenticated).toBe(true);
    expect(auth.isAdmin).toBe(true);
    expect(auth.isGradingAssistant).toBe(true);
    expect(auth.hydrated).toBe(true);
  });

  it('distinguishes a grading assistant from an admin', async () => {
    mockAuth({ authenticated: true, is_admin: false, is_grading_assistant: true });
    const auth = useAuthStore();

    await auth.hydrate();

    expect(auth.isAdmin).toBe(false);
    expect(auth.isGradingAssistant).toBe(true);
  });

  it('keeps the defaults but still hydrates when the probe fails', async () => {
    // The nav and the scoreboard's admin toggle both read this store, so a
    // failed probe must leave a usable anonymous state rather than
    // blocking on `hydrated` forever.
    mockAuth({ error: 'nope' }, 500);
    const auth = useAuthStore();

    await expect(auth.hydrate()).resolves.toBeUndefined();

    expect(auth.authenticated).toBe(false);
    expect(auth.isAdmin).toBe(false);
    expect(auth.hydrated).toBe(true);
  });

  it('survives a rejected fetch without rethrowing', async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('offline')) as never;
    const auth = useAuthStore();

    await expect(auth.hydrate()).resolves.toBeUndefined();

    expect(auth.hydrated).toBe(true);
    expect(auth.authenticated).toBe(false);
  });

  it('coerces a body with missing keys to undefined rather than crashing', async () => {
    // The store assigns straight through with no validation, so absent
    // keys land as undefined. Pinned to document the contract the backend
    // has to keep.
    mockAuth({});
    const auth = useAuthStore();

    await auth.hydrate();

    expect(auth.authenticated).toBeUndefined();
    expect(auth.isAdmin).toBeUndefined();
    expect(auth.hydrated).toBe(true);
  });

  it('refetches on a second hydrate call', async () => {
    mockAuth({ authenticated: false, is_admin: false, is_grading_assistant: false });
    const auth = useAuthStore();
    await auth.hydrate();

    mockAuth({ authenticated: true, is_admin: true, is_grading_assistant: false });
    await auth.hydrate();

    expect(auth.isAdmin).toBe(true);
  });
});
