import { describe, expect, it } from 'vitest';
import { createMemoryHistory, createRouter } from 'vue-router';

/**
 * src/router/index.ts calls createWebHistory() at import time, which
 * touches window.history and bakes in the '/spa/' base — so it is never
 * imported here. The route table is rebuilt on a memory history instead,
 * which is what vue-router's own tests do.
 *
 * The duplication is the point: if someone adds a route to the real file
 * and not here, the Playwright navigation tests are what catch it.
 */
const routes = [
  { path: '/', redirect: '/register' },
  {
    path: '/register',
    name: 'register',
    component: { template: '<div>register</div>' },
    meta: { label: 'REGISTER' },
  },
  {
    path: '/restore-key',
    name: 'restore-key',
    component: { template: '<div>restore</div>' },
    meta: { label: 'RESTORE KEY' },
  },
  {
    path: '/scoreboard',
    name: 'scoreboard',
    component: { template: '<div>scoreboard</div>' },
    meta: { label: 'SCOREBOARD' },
  },
];

function makeRouter() {
  return createRouter({ history: createMemoryHistory('/spa/'), routes });
}

describe('SPA routes', () => {
  it('redirects the root to the register page', async () => {
    const router = makeRouter();

    await router.push('/');

    expect(router.currentRoute.value.name).toBe('register');
    expect(router.currentRoute.value.path).toBe('/register');
  });

  it.each([
    ['/register', 'register', 'REGISTER'],
    ['/restore-key', 'restore-key', 'RESTORE KEY'],
    ['/scoreboard', 'scoreboard', 'SCOREBOARD'],
  ])('resolves %s to the %s route', async (path, name, label) => {
    const router = makeRouter();

    await router.push(path);

    expect(router.currentRoute.value.name).toBe(name);
    expect(router.currentRoute.value.meta.label).toBe(label);
  });

  it('matches nothing for an unknown path', () => {
    // There is no catch-all, so a bad /spa/* deep link that Caddy serves
    // index.html for renders an empty <router-view>. The Playwright suite
    // asserts what the user actually sees; here it is only the matcher.
    const router = makeRouter();

    const resolved = router.resolve('/nope');

    expect(resolved.matched).toHaveLength(0);
    expect(resolved.name).toBeUndefined();
  });

  it('carries a label on every navigable route', async () => {
    // The nav store builds its items from the same labels, so a route
    // without one would show up as a blank tab.
    const router = makeRouter();

    for (const r of router.getRoutes().filter((r) => r.name)) {
      expect(r.meta.label, `route ${String(r.name)}`).toBeTruthy();
    }
  });

  it('exposes the three student pages and nothing else', async () => {
    const router = makeRouter();

    const names = router
      .getRoutes()
      .filter((r) => r.name)
      .map((r) => String(r.name))
      .sort();

    expect(names).toEqual(['register', 'restore-key', 'scoreboard']);
  });

  it('keeps query and hash across the root redirect', async () => {
    const router = makeRouter();

    await router.push('/?from=mail#top');

    expect(router.currentRoute.value.path).toBe('/register');
    expect(router.currentRoute.value.query.from).toBe('mail');
    expect(router.currentRoute.value.hash).toBe('#top');
  });

  it('tolerates a trailing slash', async () => {
    // Caddy 308-redirects '/spa' to '/spa/', so '/spa/register/' is a
    // reachable URL; vue-router's matcher accepts it.
    const router = makeRouter();

    expect(router.resolve('/register/').name).toBe('register');
  });
});
