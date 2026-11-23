import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent } from 'vue';
import { flushPromises, type VueWrapper } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import Scoreboard from '../../src/pages/Scoreboard.vue';
import { useAuthStore } from '../../src/stores/auth';
import { mountBare } from '../helpers/mount';
import {
  apiDateOffset,
  challenge,
  DAY,
  entry,
  futureChallenge,
  HOUR,
  pastChallenge,
} from '../helpers/fixtures';

/**
 * The two chart children are replaced with prop-recording stubs. They own
 * an ECharts canvas, which zrender cannot initialise under jsdom, and
 * they are covered on their own in scoreboardCharts.spec.ts — what matters
 * here is which props the page computes for them.
 *
 * It has to be vi.mock rather than mount's `global.stubs`: Scoreboard.vue
 * imports its children in <script setup>, so they are local bindings the
 * template resolves directly and never go through the component registry
 * that stubbing by name intercepts.
 */
vi.mock('../../src/components/scoreboard/PointsOverTimeChart.vue', () => ({
  default: defineComponent({
    name: 'PointsOverTimeChart',
    props: { scoresOverTime: Object, assignmentBoundaries: Array },
    template: '<div data-test="points-chart" />',
  }),
}));

vi.mock('../../src/components/scoreboard/ChallengePlot.vue', () => ({
  default: defineComponent({
    name: 'ChallengePlot',
    props: { challengeName: String, assignments: Object, submissions: Object },
    template: '<div data-test="challenge-plot" />',
  }),
}));

function json(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  };
}

const POLL_MS = 5000;

describe('Scoreboard page', () => {
  let wrapper: VueWrapper | undefined;

  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
    vi.useRealTimers();
  });

  /**
   * Script one [config, submissions] answer pair per refresh. The last
   * pair repeats for every later poll, which is what a steady state looks
   * like.
   *
   * The round advances once both endpoints of a refresh have been served,
   * not on a particular one of them: refresh() builds the submissions
   * promise before the config promise, so the submissions request is the
   * one that goes out first and keying the round off either endpoint alone
   * serves the next round's answer to the current round.
   */
  function mockApi(
    pairs: Array<[config: ReturnType<typeof json>, subs: ReturnType<typeof json>]>,
  ) {
    let served = 0;
    const fetchMock = vi.fn((url: string) => {
      const pair = pairs[Math.min(Math.floor(served / 2), pairs.length - 1)];
      served += 1;
      return Promise.resolve(url.includes('/config') ? pair[0] : pair[1]);
    });
    globalThis.fetch = fetchMock as never;
    return fetchMock;
  }

  async function mountBoard() {
    wrapper = mountBare(Scoreboard);
    await settle();
    return wrapper;
  }

  /**
   * Mount with fake timers already installed, for the polling tests.
   * Separate from mountBoard() because the interval has to exist from the
   * first tick — installing fake timers after mount leaves the real
   * interval running and advanceTimersByTime() never fires it.
   */
  async function mountBoardWithFakeTimers() {
    vi.useFakeTimers();
    wrapper = mountBare(Scoreboard);
    await settle();
    return wrapper;
  }

  /**
   * Let one refresh complete. onMounted awaits refresh(), which awaits a
   * Promise.all of two apiGet calls, each of which awaits res.json() — so
   * a single flush lands mid-chain and the board is still unrendered.
   */
  async function settle() {
    await flushPromises();
    await flushPromises();
    await wrapper!.vm.$nextTick();
  }

  const CFG = {
    course_name: 'OS-Security',
    assignments: { A1: { ch1: challenge() } },
  };

  const SUBS = {
    ch1: { alice: [entry(5, -2 * HOUR)], bob: [entry(9, -HOUR)] },
  };

  function ok(cfg: unknown = CFG, subs: unknown = SUBS) {
    return [json(200, cfg), json(200, subs)] as [
      ReturnType<typeof json>,
      ReturnType<typeof json>,
    ];
  }

  describe('render chain', () => {
    it('shows a spinner until the first response lands', async () => {
      // Deliberately never resolves, so the pending state is observable.
      globalThis.fetch = vi.fn(() => new Promise(() => {})) as never;

      wrapper = mountBare(Scoreboard);
      await wrapper.vm.$nextTick();

      expect(wrapper!.find('[data-test="scoreboard-loading"]').exists()).toBe(true);
      expect(wrapper!.find('[data-test="scoreboard-board"]').exists()).toBe(false);
    });

    it('renders the board once config and submissions arrive', async () => {
      mockApi([ok()]);

      await mountBoard();

      expect(wrapper!.find('[data-test="scoreboard-board"]').exists()).toBe(true);
      expect(wrapper!.text()).toContain('OS-Security');
      expect(wrapper!.text()).toContain('SCOREBOARD');
    });

    it('reports the feature switched off on a 404', async () => {
      mockApi([[json(404, { error: 'disabled' }), json(404, { error: 'disabled' })]]);

      await mountBoard();

      expect(wrapper!.find('[data-test="scoreboard-disabled"]').text()).toContain(
        'currently disabled',
      );
      expect(wrapper!.find('[data-test="scoreboard-board"]').exists()).toBe(false);
    });

    it('shows the failure message on any other error', async () => {
      mockApi([[json(500, { error: 'boom' }), json(500, { error: 'boom' })]]);

      await mountBoard();

      const err = wrapper!.find('[data-test="scoreboard-error"]');
      expect(err.exists()).toBe(true);
      expect(err.text()).toContain('Failed to load scoreboard');
      expect(err.text()).toContain('boom');
    });

    it('prefers the disabled notice over the error notice', async () => {
      mockApi([[json(404, { error: 'x' }), json(404, { error: 'x' })]]);

      await mountBoard();

      expect(wrapper!.find('[data-test="scoreboard-error"]').exists()).toBe(false);
    });

    it('keeps the last good board and shows nothing new when a later poll fails', async () => {
      // Known behaviour, pinned: the error branch requires `!config`, so
      // once a board has loaded a backend outage is invisible — the stale
      // numbers just stop moving. A user has no way to tell.
      mockApi([ok(), [json(500, { error: 'boom' }), json(500, { error: 'boom' })]]);
      await mountBoardWithFakeTimers();
      expect(wrapper!.find('[data-test="scoreboard-board"]').exists()).toBe(true);

      await vi.advanceTimersByTimeAsync(POLL_MS);
      await settle();

      expect(wrapper!.find('[data-test="scoreboard-board"]').exists()).toBe(true);
      expect(wrapper!.find('[data-test="scoreboard-error"]').exists()).toBe(false);
      expect(wrapper!.findAll('[data-test="ranking-row"]').length).toBeGreaterThan(0);
    });

    it('recovers the board when a later poll succeeds after a 404', async () => {
      mockApi([[json(404, { error: 'off' }), json(404, { error: 'off' })], ok()]);
      await mountBoardWithFakeTimers();
      expect(wrapper!.find('[data-test="scoreboard-disabled"]').exists()).toBe(true);

      await vi.advanceTimersByTimeAsync(POLL_MS);
      await settle();

      expect(wrapper!.find('[data-test="scoreboard-board"]').exists()).toBe(true);
    });
  });

  describe('polling', () => {
    it('refetches on the interval', async () => {
      const fetchMock = mockApi([ok()]);
      await mountBoardWithFakeTimers();
      const afterFirst = fetchMock.mock.calls.length;

      await vi.advanceTimersByTimeAsync(POLL_MS);
      await settle();

      // Two endpoints per refresh.
      expect(fetchMock.mock.calls.length).toBe(afterFirst * 2);
    });

    it('does not refetch before the interval elapses', async () => {
      const fetchMock = mockApi([ok()]);
      await mountBoardWithFakeTimers();
      const afterFirst = fetchMock.mock.calls.length;

      await vi.advanceTimersByTimeAsync(POLL_MS - 1);
      await settle();

      expect(fetchMock.mock.calls.length).toBe(afterFirst);
    });

    it('picks up a new submission without a reload', async () => {
      mockApi([
        ok(),
        ok(CFG, { ch1: { alice: [entry(5, -2 * HOUR), entry(20, -HOUR)] } }),
      ]);
      await mountBoardWithFakeTimers();

      await vi.advanceTimersByTimeAsync(POLL_MS);
      await settle();

      expect(wrapper!.find('[data-test="ranking-table"]').text()).toContain('20.00');
    });

    it('stops polling once unmounted', async () => {
      const fetchMock = mockApi([ok()]);
      await mountBoardWithFakeTimers();
      const atUnmount = fetchMock.mock.calls.length;

      wrapper!.unmount();
      wrapper = undefined;
      await vi.advanceTimersByTimeAsync(POLL_MS * 3);

      expect(fetchMock.mock.calls.length).toBe(atUnmount);
    });
  });

  describe('ranking tables', () => {
    it('ranks teams best first in the overall table', async () => {
      mockApi([ok()]);

      await mountBoard();

      const rows = wrapper!.findAll('[data-test="ranking-table"]')[0].findAll(
        '[data-test="ranking-row"]',
      );
      expect(rows.map((r) => r.find('.term-team').text())).toEqual(['bob', 'alice']);
    });

    it('renders three tables: overall, assignment and challenge', async () => {
      mockApi([ok()]);

      await mountBoard();

      expect(wrapper!.findAll('[data-test="ranking-table"]')).toHaveLength(3);
    });

    it('hides badges on the assignment and challenge tables only', async () => {
      mockApi([ok()]);

      await mountBoard();

      const tables = wrapper!.findAll('[data-test="ranking-table"]');
      expect(tables[0].findAll('th')).toHaveLength(4);
      expect(tables[1].findAll('th')).toHaveLength(3);
      expect(tables[2].findAll('th')).toHaveLength(3);
    });

    it('scopes the challenge table to the selected challenge', async () => {
      mockApi([
        ok(
          {
            course_name: 'C',
            assignments: { A1: { ch1: challenge(), ch2: challenge() } },
          },
          {
            ch1: { alice: [entry(5)] },
            ch2: { bob: [entry(7)] },
          },
        ),
      ]);

      await mountBoard();

      const challengeTable = wrapper!.findAll('[data-test="ranking-table"]')[2];
      expect(challengeTable.text()).toContain('alice');
      expect(challengeTable.text()).not.toContain('bob');
    });

    it('shows the empty placeholder when nobody has scored', async () => {
      mockApi([ok(CFG, { ch1: {} })]);

      await mountBoard();

      expect(wrapper!.findAll('[data-test="ranking-empty"]').length).toBeGreaterThan(0);
    });
  });

  describe('assignment tabs', () => {
    const multi = {
      course_name: 'C',
      assignments: {
        A1: { ch1: pastChallenge() },
        A2: { ch2: challenge() },
        A3: { ch3: futureChallenge() },
      },
    };

    it('lists one tab per assignment', async () => {
      mockApi([ok(multi, {})]);

      await mountBoard();

      const tabs = wrapper!.findAll('[data-test="assignment-tabs"] a');
      expect(tabs.map((t) => t.text())).toEqual(['A1', 'A2', 'A3']);
    });

    it('starts on the assignment whose window is open', async () => {
      mockApi([ok(multi, {})]);

      await mountBoard();

      expect(
        wrapper!.find('[data-test="assignment-tab-A2"]').classes(),
      ).toContain('is-current');
    });

    it('disables an assignment that has not started yet', async () => {
      mockApi([ok(multi, {})]);

      await mountBoard();

      expect(
        wrapper!.find('[data-test="assignment-tab-A3"]').classes(),
      ).toContain('is-disabled');
      expect(
        wrapper!.find('[data-test="assignment-tab-A1"]').classes(),
      ).not.toContain('is-disabled');
    });

    it('lets the user switch to a started assignment', async () => {
      mockApi([ok(multi, {})]);
      await mountBoard();

      await wrapper!.find('[data-test="assignment-tab-A1"]').trigger('click');

      expect(
        wrapper!.find('[data-test="assignment-tab-A1"]').classes(),
      ).toContain('is-current');
    });

    it('refuses a click on a not-yet-started assignment', async () => {
      mockApi([ok(multi, {})]);
      await mountBoard();

      await wrapper!.find('[data-test="assignment-tab-A3"]').trigger('click');

      expect(
        wrapper!.find('[data-test="assignment-tab-A3"]').classes(),
      ).not.toContain('is-current');
      expect(
        wrapper!.find('[data-test="assignment-tab-A2"]').classes(),
      ).toContain('is-current');
    });

    it('keeps the user on their chosen assignment across a poll', async () => {
      // Selections are kept in their own refs precisely so the 5-second
      // refresh does not yank the user back to the active assignment.
      mockApi([ok(multi, {})]);
      await mountBoardWithFakeTimers();
      await wrapper!.find('[data-test="assignment-tab-A1"]').trigger('click');

      await vi.advanceTimersByTimeAsync(POLL_MS);
      await settle();

      expect(wrapper!.find('[data-test="assignment-tab-A1"]').classes()).toContain(
        'is-current',
      );
    });

    it('falls back to the first assignment when every window is in the future', async () => {
      mockApi([
        ok({
          course_name: 'C',
          assignments: {
            Z: { c: futureChallenge(2 * DAY) },
            Y: { c: futureChallenge(DAY) },
          },
        }, {}),
      ]);

      await mountBoard();

      // getActiveAssignmentName picks the soonest upcoming one.
      expect(wrapper!.find('[data-test="assignment-tab-Y"]').classes()).toContain(
        'is-current',
      );
    });

    it('renders no tabs and no challenge section with no assignments', async () => {
      mockApi([ok({ course_name: 'C', assignments: {} }, {})]);

      await mountBoard();

      expect(wrapper!.findAll('[data-test="assignment-tabs"] a')).toHaveLength(0);
      expect(wrapper!.find('[data-test="challenge-plot"]').exists()).toBe(false);
    });
  });

  describe('challenge tabs', () => {
    const twoChallenges = {
      course_name: 'C',
      assignments: { A1: { ch1: challenge(), ch2: challenge() } },
    };

    it('lists one tab per challenge in the active assignment', async () => {
      mockApi([ok(twoChallenges, {})]);

      await mountBoard();

      expect(
        wrapper!.findAll('[data-test="challenge-tabs"] a').map((t) => t.text()),
      ).toEqual(['ch1', 'ch2']);
    });

    it('starts on the first challenge', async () => {
      mockApi([ok(twoChallenges, {})]);

      await mountBoard();

      expect(wrapper!.find('[data-test="challenge-tab-ch1"]').classes()).toContain(
        'is-current',
      );
    });

    it('switches the plot when another challenge is picked', async () => {
      mockApi([ok(twoChallenges, {})]);
      await mountBoard();

      await wrapper!.find('[data-test="challenge-tab-ch2"]').trigger('click');

      expect(wrapper!.find('[data-test="challenge-tab-ch2"]').classes()).toContain(
        'is-current',
      );
      expect(
        wrapper!.findComponent({ name: 'ChallengePlot' }).props('challengeName'),
      ).toBe('ch2');
    });

    it('remembers the challenge choice per assignment', async () => {
      mockApi([
        ok(
          {
            course_name: 'C',
            assignments: {
              A1: { ch1: challenge(), ch2: challenge() },
              A2: { ch3: challenge() },
            },
          },
          {},
        ),
      ]);
      await mountBoard();
      await wrapper!.find('[data-test="challenge-tab-ch2"]').trigger('click');

      await wrapper!.find('[data-test="assignment-tab-A2"]').trigger('click');
      await wrapper!.find('[data-test="assignment-tab-A1"]').trigger('click');

      expect(wrapper!.find('[data-test="challenge-tab-ch2"]').classes()).toContain(
        'is-current',
      );
    });
  });

  describe('countdown', () => {
    it('shows the remaining time for the active assignment', async () => {
      mockApi([ok()]);

      await mountBoard();

      expect(wrapper!.find('.term-countdown-label').text()).toContain('Remaining:');
    });

    it('reads the window off the assignment first challenge', async () => {
      mockApi([
        ok(
          {
            course_name: 'C',
            assignments: {
              A1: {
                ch1: challenge({
                  start: apiDateOffset(-HOUR),
                  end: apiDateOffset(HOUR),
                }),
              },
            },
          },
          {},
        ),
      ]);

      await mountBoard();

      // Half the window gone.
      expect(wrapper!.find('.term-countdown-fill').attributes('style')).toMatch(
        /width: (49|50|51)/,
      );
    });

    it('omits the countdown when the assignment has no challenges', async () => {
      mockApi([ok({ course_name: 'C', assignments: { A1: {} } }, {})]);

      await mountBoard();

      expect(wrapper!.find('.term-countdown').exists()).toBe(false);
    });
  });

  describe('chart props', () => {
    it('passes the computed score timeline to the points chart', async () => {
      mockApi([ok()]);

      await mountBoard();

      const scores = wrapper!
        .findComponent({ name: 'PointsOverTimeChart' })
        .props('scoresOverTime') as Record<string, unknown[]>;
      expect(Object.keys(scores).sort()).toEqual(['alice', 'bob']);
    });

    it('passes only boundaries that have already been reached', async () => {
      // A future assignment's start line would be drawn beyond the data,
      // stretching the axis for no reason.
      mockApi([
        ok(
          {
            course_name: 'C',
            assignments: {
              Past: { a: pastChallenge() },
              Future: { b: futureChallenge() },
            },
          },
          {},
        ),
      ]);

      await mountBoard();

      const boundaries = wrapper!
        .findComponent({ name: 'PointsOverTimeChart' })
        .props('assignmentBoundaries') as Array<{ name: string }>;
      expect(boundaries.map((b) => b.name)).toEqual(['Past']);
    });

    it('hands the plot the whole assignments and submissions maps', async () => {
      mockApi([ok()]);

      await mountBoard();

      const plot = wrapper!.findComponent({ name: 'ChallengePlot' });
      expect(plot.props('challengeName')).toBe('ch1');
      expect(plot.props('assignments')).toEqual(CFG.assignments);
      expect(plot.props('submissions')).toEqual(SUBS);
    });
  });

  describe('admin view toggle', () => {
    it('stays hidden for an anonymous visitor', async () => {
      mockApi([ok()]);

      await mountBoard();

      expect(wrapper!.find('[data-test="admin-toggle"]').exists()).toBe(false);
    });

    it('appears for an admin', async () => {
      mockApi([ok()]);
      useAuthStore().isAdmin = true;

      await mountBoard();

      const toggle = wrapper!.find('[data-test="admin-toggle"]');
      expect(toggle.exists()).toBe(true);
      expect(toggle.text()).toBe('[ user view ]');
    });

    it('switches to the admin submissions endpoint when clicked', async () => {
      const fetchMock = mockApi([ok()]);
      useAuthStore().isAdmin = true;
      await mountBoard();

      await wrapper!.find('[data-test="admin-toggle"]').trigger('click');
      await flushPromises();

      const urls = fetchMock.mock.calls.map((c) => String(c[0]));
      expect(urls).toContain('/api/scoreboard/submissions/admin');
      expect(wrapper!.find('[data-test="admin-toggle"]').text()).toBe('[ admin view ]');
    });

    it('switches back to the public endpoint on a second click', async () => {
      const fetchMock = mockApi([ok()]);
      useAuthStore().isAdmin = true;
      await mountBoard();
      await wrapper!.find('[data-test="admin-toggle"]').trigger('click');
      await flushPromises();
      fetchMock.mockClear();

      await wrapper!.find('[data-test="admin-toggle"]').trigger('click');
      await flushPromises();

      const urls = fetchMock.mock.calls.map((c) => String(c[0]));
      expect(urls).toContain('/api/scoreboard/submissions');
      expect(urls).not.toContain('/api/scoreboard/submissions/admin');
    });

    it('keeps polling the admin endpoint after the toggle', async () => {
      const fetchMock = mockApi([ok()]);
      useAuthStore().isAdmin = true;
      await mountBoardWithFakeTimers();
      await wrapper!.find('[data-test="admin-toggle"]').trigger('click');
      await flushPromises();
      fetchMock.mockClear();

      await vi.advanceTimersByTimeAsync(POLL_MS);
      await settle();

      expect(fetchMock.mock.calls.map((c) => String(c[0]))).toContain(
        '/api/scoreboard/submissions/admin',
      );
    });

    it('uses the public endpoint for a non-admin', async () => {
      const fetchMock = mockApi([ok()]);

      await mountBoard();

      const urls = fetchMock.mock.calls.map((c) => String(c[0]));
      expect(urls).toContain('/api/scoreboard/submissions');
      expect(urls).not.toContain('/api/scoreboard/submissions/admin');
    });
  });
});
