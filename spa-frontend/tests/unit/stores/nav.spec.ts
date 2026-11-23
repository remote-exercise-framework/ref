import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useNavStore } from '../../../src/stores/nav';

const META = {
  course_name: 'OS-Security',
  registration_enabled: true,
  groups_enabled: false,
  max_group_size: 1,
  groups: [],
  password_rules: { min_length: 12, min_classes: 3 },
  mat_num_regex: '.*',
};

function json(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

/**
 * hydrate() calls the registration meta first, then the scoreboard config,
 * each in its own try block — so the two outcomes are scripted in order.
 */
function mockFetch(
  metaResult: ReturnType<typeof json> | Error,
  sbResult: ReturnType<typeof json> | Error,
) {
  const queue: Array<ReturnType<typeof json> | Error> = [metaResult, sbResult];
  globalThis.fetch = vi.fn(() => {
    const next = queue.shift();
    return next instanceof Error ? Promise.reject(next) : Promise.resolve(next);
  }) as never;
}

function labels(items: { label: string }[]) {
  return items.map((i) => i.label);
}

describe('nav store', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('starts with a placeholder course and the scoreboard hidden', () => {
    const nav = useNavStore();

    expect(nav.courseName).toBe('REF');
    expect(labels(nav.visibleItems)).toEqual(['REGISTER', 'RESTORE KEY']);
    expect(nav.hydrated).toBe(false);
  });

  it('adopts the course name and reveals the scoreboard when both probes succeed', async () => {
    mockFetch(json(200, META), json(200, { course_name: 'X', assignments: {} }));
    const nav = useNavStore();

    await nav.hydrate();

    expect(nav.courseName).toBe('OS-Security');
    expect(labels(nav.visibleItems)).toEqual(['REGISTER', 'RESTORE KEY', 'SCOREBOARD']);
    expect(nav.hydrated).toBe(true);
  });

  it('hides the register item when registration is disabled', async () => {
    mockFetch(
      json(200, { ...META, registration_enabled: false }),
      json(200, { course_name: 'X', assignments: {} }),
    );
    const nav = useNavStore();

    await nav.hydrate();

    expect(labels(nav.visibleItems)).toEqual(['RESTORE KEY', 'SCOREBOARD']);
  });

  it('hides the scoreboard on a 404', async () => {
    mockFetch(json(200, META), json(404, { error: 'not found' }));
    const nav = useNavStore();

    await nav.hydrate();

    expect(labels(nav.visibleItems)).not.toContain('SCOREBOARD');
  });

  it('also hides the scoreboard on a 500', async () => {
    // The catch is deliberately broad: any failure hides the tab, not just
    // the "disabled" 404. So a backend outage looks identical to the
    // feature being switched off.
    mockFetch(json(200, META), json(500, { error: 'boom' }));
    const nav = useNavStore();

    await nav.hydrate();

    expect(labels(nav.visibleItems)).not.toContain('SCOREBOARD');
    expect(nav.hydrated).toBe(true);
  });

  it('reveals the scoreboard even when the registration probe failed', async () => {
    // The two try blocks are independent.
    mockFetch(new Error('meta down'), json(200, { course_name: 'X', assignments: {} }));
    const nav = useNavStore();

    await nav.hydrate();

    expect(nav.courseName).toBe('REF');
    expect(labels(nav.visibleItems)).toContain('SCOREBOARD');
  });

  it('keeps the course name when only the scoreboard probe failed', async () => {
    mockFetch(json(200, META), new Error('sb down'));
    const nav = useNavStore();

    await nav.hydrate();

    expect(nav.courseName).toBe('OS-Security');
    expect(labels(nav.visibleItems)).not.toContain('SCOREBOARD');
  });

  it('hydrates even when both probes fail', async () => {
    mockFetch(new Error('a'), new Error('b'));
    const nav = useNavStore();

    await nav.hydrate();

    expect(nav.hydrated).toBe(true);
    expect(labels(nav.visibleItems)).toEqual(['REGISTER', 'RESTORE KEY']);
  });
});
