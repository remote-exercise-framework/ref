import { afterEach, beforeEach, vi } from 'vitest';
import ResizeObserver from 'resize-observer-polyfill';

// --- jsdom gaps -----------------------------------------------------------

// chartSetup.mountChart constructs one unconditionally.
globalThis.ResizeObserver = ResizeObserver as never;

/**
 * A controllable MediaQueryList. useTheme's systemPrefersLight() and
 * Vuetify's useDisplay() both go through matchMedia, and jsdom does not
 * implement it. `matches` defaults to false, i.e. "(prefers-color-scheme:
 * light)" is false, which matches the app's hackerDark default.
 *
 * Call `__set(true)` on an instance to flip the value and notify every
 * registered listener — that is how the auto-mode theme tests drive a
 * system preference change without reloading the module.
 */
export type TestMediaQueryList = MediaQueryList & {
  __set(next: boolean): void;
  /** How many change listeners are currently registered. */
  __listenerCount(): number;
  /** Re-evaluate the query and notify listeners if the answer moved. */
  __reevaluate(): void;
};

const mediaQueryLists = new Set<TestMediaQueryList>();

/** What '(prefers-color-scheme: light)' queries report. */
let prefersLight = false;

/**
 * Answer a media query from the simulated environment. Only the two kinds
 * the app actually asks for are evaluated:
 *
 *   - `(prefers-color-scheme: light)` from useTheme's auto mode
 *   - `(min-width:)` / `(max-width:)` from Vuetify's useDisplay
 *
 * Vuetify derives its breakpoint *name* from these queries rather than
 * from window.innerWidth, so a stub that answers false to everything
 * pins the whole app at `xs` no matter how wide the window is — which
 * silently made every responsive test pass for the wrong reason.
 */
function evaluateQuery(query: string): boolean {
  if (query.includes('prefers-color-scheme: light')) return prefersLight;
  if (query.includes('prefers-color-scheme: dark')) return !prefersLight;

  let result: boolean | null = null;
  for (const [, bound, raw] of query.matchAll(/\((min|max)-width:\s*([\d.]+)px\)/g)) {
    const px = Number(raw);
    const ok = bound === 'min' ? window.innerWidth >= px : window.innerWidth <= px;
    result = result === null ? ok : result && ok;
  }
  return result ?? false;
}

function makeMediaQueryList(query: string): TestMediaQueryList {
  const listeners = new Set<(e: MediaQueryListEvent) => void>();
  // `matches` is a getter so it tracks the simulated environment, with an
  // override for __set. Built as a loose literal because MediaQueryList
  // declares `matches` readonly.
  let override: boolean | null = null;
  let lastSeen = evaluateQuery(query);

  function current(): boolean {
    return override ?? evaluateQuery(query);
  }

  function notifyIfChanged() {
    const next = current();
    if (next === lastSeen) return;
    lastSeen = next;
    listeners.forEach((l) => l({ matches: next, media: query } as MediaQueryListEvent));
  }

  const state: Record<string, unknown> = {
    media: query,
    get matches() {
      return current();
    },
    onchange: null,
    addEventListener: (_type: string, l: (e: MediaQueryListEvent) => void) =>
      void listeners.add(l),
    removeEventListener: (_type: string, l: (e: MediaQueryListEvent) => void) =>
      void listeners.delete(l),
    addListener: (l: (e: MediaQueryListEvent) => void) => void listeners.add(l),
    removeListener: (l: (e: MediaQueryListEvent) => void) => void listeners.delete(l),
    dispatchEvent: () => true,
    __set(next: boolean) {
      override = next;
      notifyIfChanged();
    },
    __listenerCount: () => listeners.size,
    __reevaluate: notifyIfChanged,
  };
  const mql = state as unknown as TestMediaQueryList;
  mediaQueryLists.add(mql);
  return mql;
}

/**
 * Resize the simulated viewport and let every live media query react, the
 * way a real browser would. Use this instead of assigning
 * window.innerWidth directly — Vuetify's breakpoints come from
 * matchMedia, so a bare assignment changes `display.width` but not
 * `display.name`.
 */
export function setViewportWidth(width: number, height = 768) {
  window.innerWidth = width;
  window.innerHeight = height;
  mediaQueryLists.forEach((mql) => mql.__reevaluate());
  window.dispatchEvent(new Event('resize'));
}

/** Every MediaQueryList handed out since the last test started. */
export function lastMediaQueryList(): TestMediaQueryList {
  const all = [...mediaQueryLists];
  if (all.length === 0) throw new Error('no matchMedia call was made');
  return all[all.length - 1];
}

/**
 * Change listeners registered across every MediaQueryList handed out so
 * far. Summed rather than read off one list because each matchMedia call
 * returns a fresh object, so a module that queries repeatedly spreads its
 * (at most one) listener over several of them.
 */
export function totalMediaQueryListeners(): number {
  let n = 0;
  mediaQueryLists.forEach((mql) => {
    n += mql.__listenerCount();
  });
  return n;
}

/**
 * Make the system report a light (or dark) colour-scheme preference for
 * every subsequent matchMedia call, and update any MediaQueryList already
 * handed out so a listener registered before the change still fires.
 */
export function setSystemPrefersLight(next: boolean) {
  prefersLight = next;
  mediaQueryLists.forEach((mql) => mql.__reevaluate());
}

/**
 * Install a fresh matchMedia. Called once at module load and again before
 * every test: a test that replaces the implementation (or a stale
 * MediaQueryList holding a listener into a disposed module instance) must
 * not leak into the next one.
 */
function installMatchMedia() {
  prefersLight = false;
  mediaQueryLists.clear();
  // jsdom's own default, restored so a resize test cannot leak a width.
  window.innerWidth = 1024;
  window.innerHeight = 768;
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: vi.fn((q: string) => makeMediaQueryList(q)),
  });
}

installMatchMedia();

// KeyDownloadCard.copy() needs this; jsdom has no clipboard at all.
Object.defineProperty(navigator, 'clipboard', {
  writable: true,
  configurable: true,
  value: { writeText: vi.fn().mockResolvedValue(undefined) },
});

// Vuetify's overlay location strategy reads the global visualViewport
// when positioning a menu. jsdom does not implement it, and the resulting
// ReferenceError surfaces only as "Unhandled error during execution of
// watcher callback" with the menu silently never opening.
if (window.visualViewport == null) {
  Object.defineProperty(window, 'visualViewport', {
    writable: true,
    configurable: true,
    value: {
      // jsdom's default window is 1024x768; Vuetify only reads these to
      // decide where a menu fits, and the component tests do not assert
      // on the resulting coordinates.
      width: 1024,
      height: 768,
      offsetLeft: 0,
      offsetTop: 0,
      pageLeft: 0,
      pageTop: 0,
      scale: 1,
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => true,
    },
  });
}

// Vuetify calls this while positioning overlays.
if (!Element.prototype.animate) {
  Element.prototype.animate = (() => ({
    finished: Promise.resolve(),
    cancel() {},
  })) as never;
}

// --- per-test hygiene -----------------------------------------------------

beforeEach(() => {
  // api/client.ts has no baseURL, so an unmocked call would reach jsdom's
  // real fetch and hang the test until the timeout. Fail loudly instead.
  globalThis.fetch = vi.fn(() => {
    throw new Error('unmocked fetch — stub globalThis.fetch in the test');
  }) as never;
  localStorage.clear();
  installMatchMedia();
});

afterEach(() => {
  // mountInApp attaches to the body, so anything left behind would leak
  // into the next test's DOM queries. body.className matters on its own:
  // useTheme.applyBodyClass writes it and chartSetup.isLightTheme reads it.
  document.body.innerHTML = '';
  document.body.className = '';
  vi.useRealTimers();
});
