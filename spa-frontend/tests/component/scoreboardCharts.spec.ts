import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { VueWrapper } from '@vue/test-utils';
import type { EChartsOption } from 'echarts';

/**
 * Both chart components keep buildOption()/buildSeries() private. Rather
 * than export them for the tests, this file mocks ./chartSetup wholesale
 * and reads the option object the component hands to setOption() — which
 * covers the builders *and* the tooltip formatter closures, with no
 * canvas involved.
 *
 * vi.mock is hoisted, so it has to be declared before the component
 * imports; the components are therefore imported dynamically inside the
 * tests.
 */
const setOption = vi.fn();
const dispose = vi.fn();
const disconnect = vi.fn();
const themeListeners = new Set<() => void>();

vi.mock('../../src/components/scoreboard/chartSetup', () => ({
  mountChart: vi.fn(() => ({
    chart: { setOption, getOption: () => ({}), dispose },
    resizeObserver: { disconnect },
  })),
  unmountChart: vi.fn(),
  applyPreservedState: vi.fn((_chart: unknown, option: EChartsOption) => option),
  buildCommonOptions: vi.fn((xMin: number, xMax?: number) => ({
    xAxis: { type: 'time', min: xMin, max: xMax },
    tooltip: { backgroundColor: 'rgb(1,2,3)' },
    dataZoom: [{ id: 'inside-x' }, { id: 'slider-x' }],
  })),
  getMarkLineColors: vi.fn(() => ({ line: 'rgb(9,9,9)', label: 'rgb(8,8,8)' })),
  getTeamColor: vi.fn((team: string) => `color-${team}`),
  getTeamSymbol: vi.fn((team: string) => `symbol-${team}`),
  formatTooltipDate: vi.fn((v: number) => `D${v}`),
  onThemeChange: vi.fn((fn: () => void) => {
    themeListeners.add(fn);
    return () => themeListeners.delete(fn);
  }),
}));

type Series = {
  id: string;
  name: string;
  symbol: string;
  data: Array<{ value: [number, number]; tasks?: Record<string, number | null> }>;
  lineStyle: { color: string };
  itemStyle: { color: string };
  markLine?: {
    data: Array<Record<string, number>>;
    label: { formatter: unknown };
    lineStyle: { color: string };
  };
};

/** The option object from the Nth setOption call (0-based). */
function optionAt(n = 0): EChartsOption & { series: Series[] } {
  expect(setOption.mock.calls.length).toBeGreaterThan(n);
  return setOption.mock.calls[n][0];
}

function seriesAt(n = 0): Series[] {
  return optionAt(n).series;
}

/** Call the tooltip formatter the component built. */
function tooltipFormatter(n = 0): (raw: unknown) => string {
  const tooltip = optionAt(n).tooltip as { formatter: (raw: unknown) => string };
  return tooltip.formatter;
}

describe('PointsOverTimeChart', () => {
  let wrapper: VueWrapper | undefined;

  beforeEach(() => {
    setOption.mockClear();
    themeListeners.clear();
  });

  afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
  });

  async function mountChart(props: {
    scoresOverTime: Record<string, Array<{ time: number; score: number }>>;
    assignmentBoundaries?: Array<{ name: string; date: Date }>;
  }) {
    const { mountBare } = await import('../helpers/mount');
    const Comp = (await import('../../src/components/scoreboard/PointsOverTimeChart.vue'))
      .default;
    wrapper = mountBare(Comp, {
      props: { assignmentBoundaries: [], ...props },
    });
    await wrapper.vm.$nextTick();
    return wrapper;
  }

  it('renders one series per team, named after the team', async () => {
    await mountChart({
      scoresOverTime: {
        alice: [{ time: 1000, score: 5 }],
        bob: [{ time: 2000, score: 3 }],
      },
    });

    const series = seriesAt();
    expect(series.map((s) => s.name)).toEqual(['alice', 'bob']);
    expect(series.map((s) => s.id)).toEqual(['team-alice', 'team-bob']);
  });

  it('takes each team its colour and symbol from chartSetup', async () => {
    await mountChart({ scoresOverTime: { alice: [{ time: 1000, score: 5 }] } });

    const s = seriesAt()[0];
    expect(s.lineStyle.color).toBe('color-alice');
    expect(s.itemStyle.color).toBe('color-alice');
    expect(s.symbol).toBe('symbol-alice');
  });

  it('maps each score into a [time, score] pair', async () => {
    await mountChart({
      scoresOverTime: {
        alice: [
          { time: 1000, score: 5 },
          { time: 2000, score: 9 },
        ],
      },
    });

    expect(seriesAt()[0].data).toEqual([{ value: [1000, 5] }, { value: [2000, 9] }]);
  });

  it('pads the x axis by 2% of the data range', async () => {
    await mountChart({
      scoresOverTime: { alice: [{ time: 0, score: 1 }, { time: 1000, score: 2 }] },
    });

    const axis = optionAt().xAxis as { min: number; max: number };
    expect(axis.min).toBe(-20);
    expect(axis.max).toBe(1020);
  });

  it('does not pad when every point shares a timestamp', async () => {
    await mountChart({ scoresOverTime: { alice: [{ time: 5000, score: 1 }] } });

    const axis = optionAt().xAxis as { min: number; max: number };
    expect(axis.min).toBe(5000);
    expect(axis.max).toBe(5000);
  });

  it('falls back to a zero range with no data at all', async () => {
    await mountChart({ scoresOverTime: {} });

    const axis = optionAt().xAxis as { min: number; max: number };
    expect(axis.min).toBe(0);
    expect(axis.max).toBe(0);
    expect(seriesAt()).toEqual([]);
  });

  it('drops the zoom controls when there is only one point', async () => {
    // ECharts draws a broken slider for a single point.
    await mountChart({ scoresOverTime: { alice: [{ time: 1000, score: 5 }] } });

    expect(optionAt().dataZoom).toEqual([]);
  });

  it('keeps the zoom controls once there are two points', async () => {
    await mountChart({
      scoresOverTime: { alice: [{ time: 1000, score: 5 }, { time: 2000, score: 6 }] },
    });

    expect(optionAt().dataZoom).toHaveLength(2);
  });

  it('counts points across teams towards the zoom threshold', async () => {
    await mountChart({
      scoresOverTime: {
        alice: [{ time: 1000, score: 5 }],
        bob: [{ time: 2000, score: 5 }],
      },
    });

    expect(optionAt().dataZoom).toHaveLength(2);
  });

  describe('assignment boundaries', () => {
    const boundaries = [
      { name: 'A1', date: new Date(1000) },
      { name: 'A2', date: new Date(5000) },
    ];

    it('hangs the boundary marks off the first series only', async () => {
      await mountChart({
        scoresOverTime: {
          alice: [{ time: 2000, score: 5 }],
          bob: [{ time: 3000, score: 5 }],
        },
        assignmentBoundaries: boundaries,
      });

      const series = seriesAt();
      expect(series[0].markLine?.data).toEqual([{ xAxis: 1000 }, { xAxis: 5000 }]);
      expect(series[1].markLine).toBeUndefined();
    });

    it('omits the mark line when there are no boundaries', async () => {
      await mountChart({ scoresOverTime: { alice: [{ time: 2000, score: 5 }] } });

      expect(seriesAt()[0].markLine).toBeUndefined();
    });

    it('labels each boundary with its assignment name', async () => {
      await mountChart({
        scoresOverTime: { alice: [{ time: 2000, score: 5 }] },
        assignmentBoundaries: boundaries,
      });

      const formatter = seriesAt()[0].markLine!.label.formatter as (a: {
        dataIndex: number;
      }) => string;
      expect(formatter({ dataIndex: 0 })).toBe('A1');
      expect(formatter({ dataIndex: 1 })).toBe('A2');
    });

    it('falls back to a positional name for an out-of-range index', async () => {
      await mountChart({
        scoresOverTime: { alice: [{ time: 2000, score: 5 }] },
        assignmentBoundaries: boundaries,
      });

      const formatter = seriesAt()[0].markLine!.label.formatter as (a: {
        dataIndex: number;
      }) => string;
      expect(formatter({ dataIndex: 9 })).toBe('Assignment 10');
    });

    it('widens the axis to include a boundary outside the data range', async () => {
      await mountChart({
        scoresOverTime: { alice: [{ time: 2000, score: 5 }] },
        assignmentBoundaries: [{ name: 'A1', date: new Date(100) }],
      });

      const axis = optionAt().xAxis as { min: number; max: number };
      expect(axis.min).toBeLessThan(100);
      expect(axis.max).toBeGreaterThan(2000);
    });

    it('draws boundaries even with no team data', async () => {
      await mountChart({
        scoresOverTime: {},
        assignmentBoundaries: boundaries,
      });

      // No series means nowhere to hang the mark line, so the boundaries
      // only affect the axis.
      const axis = optionAt().xAxis as { min: number; max: number };
      expect(axis.min).toBeLessThanOrEqual(1000);
      expect(axis.max).toBeGreaterThanOrEqual(5000);
    });
  });

  describe('tooltip', () => {
    it('heads the tooltip with the formatted timestamp', async () => {
      await mountChart({ scoresOverTime: { alice: [{ time: 1000, score: 5 }] } });

      const out = tooltipFormatter()([
        { axisValue: 1000, data: { value: [1000, 5] }, marker: 'M', seriesName: 'alice' },
      ]);

      expect(out.split('<br/>')[0]).toBe('D1000');
    });

    it('lists one line per team at that timestamp, scores to two decimals', async () => {
      await mountChart({ scoresOverTime: { alice: [{ time: 1000, score: 5 }] } });

      const out = tooltipFormatter()([
        { axisValue: 1000, data: { value: [1000, 5] }, marker: 'M', seriesName: 'alice' },
        { axisValue: 1000, data: { value: [1000, 3.456] }, marker: 'N', seriesName: 'bob' },
      ]);

      expect(out.split('<br/>')).toEqual(['D1000', 'Malice: 5.00', 'Nbob: 3.46']);
    });

    it('accepts a single non-array param', async () => {
      // ECharts passes an object rather than an array for some triggers.
      await mountChart({ scoresOverTime: { alice: [{ time: 1000, score: 5 }] } });

      const out = tooltipFormatter()({
        axisValue: 1000,
        data: { value: [1000, 5] },
        seriesName: 'alice',
      });

      expect(out).toContain('alice: 5.00');
    });

    it('returns an empty string for no params', async () => {
      await mountChart({ scoresOverTime: { alice: [{ time: 1000, score: 5 }] } });

      expect(tooltipFormatter()([])).toBe('');
    });

    it('substitutes zero for a missing score', async () => {
      await mountChart({ scoresOverTime: { alice: [{ time: 1000, score: 5 }] } });

      const out = tooltipFormatter()([{ axisValue: 1000, seriesName: 'alice' }]);

      expect(out).toContain('alice: 0.00');
    });
  });

  describe('lifecycle', () => {
    it('re-renders when the scores change', async () => {
      await mountChart({ scoresOverTime: { alice: [{ time: 1000, score: 5 }] } });
      const before = setOption.mock.calls.length;

      await wrapper!.setProps({
        scoresOverTime: { alice: [{ time: 1000, score: 5 }, { time: 2000, score: 8 }] },
      });

      expect(setOption.mock.calls.length).toBeGreaterThan(before);
      expect(seriesAt(setOption.mock.calls.length - 1)[0].data).toHaveLength(2);
    });

    it('re-renders when the theme changes', async () => {
      await mountChart({ scoresOverTime: { alice: [{ time: 1000, score: 5 }] } });
      const before = setOption.mock.calls.length;

      themeListeners.forEach((fn) => fn());

      expect(setOption.mock.calls.length).toBe(before + 1);
    });

    it('unsubscribes from theme changes on unmount', async () => {
      await mountChart({ scoresOverTime: { alice: [{ time: 1000, score: 5 }] } });

      wrapper!.unmount();
      wrapper = undefined;

      expect(themeListeners.size).toBe(0);
    });

    it('replaces rather than merges the option', async () => {
      // A team dropping out of the ranking has to remove its series, which
      // a merge would leave behind.
      await mountChart({ scoresOverTime: { alice: [{ time: 1000, score: 5 }] } });

      expect(setOption.mock.calls[0][1]).toEqual({ notMerge: true });
    });
  });
});

describe('ChallengePlot', () => {
  let wrapper: VueWrapper | undefined;

  beforeEach(() => {
    setOption.mockClear();
    themeListeners.clear();
  });

  afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
  });

  /** "DD/MM/YYYY HH:MM:SS", the format the API emits. */
  function ts(d: Date): string {
    const p = (n: number) => String(n).padStart(2, '0');
    return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()} ${p(
      d.getHours(),
    )}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }

  const T1 = new Date(2024, 0, 1, 10, 0, 0);
  const T2 = new Date(2024, 0, 1, 11, 0, 0);
  const T3 = new Date(2024, 0, 1, 12, 0, 0);

  async function mountPlot(props: {
    challengeName?: string;
    assignments?: Record<string, Record<string, unknown>>;
    submissions?: Record<
      string,
      Record<string, Array<{ ts: string; score: number; tasks?: Record<string, number | null> }>>
    >;
  }) {
    const { mountBare } = await import('../helpers/mount');
    const Comp = (await import('../../src/components/scoreboard/ChallengePlot.vue')).default;
    wrapper = mountBare(Comp, {
      props: {
        challengeName: 'ch1',
        assignments: {},
        submissions: {},
        ...props,
      },
    });
    await wrapper.vm.$nextTick();
    return wrapper;
  }

  it('renders one series per team that scored above zero', async () => {
    await mountPlot({
      submissions: {
        ch1: {
          alice: [{ ts: ts(T1), score: 5 }],
          bob: [{ ts: ts(T1), score: 7 }],
        },
      },
    });

    expect(seriesAt().map((s) => s.name)).toEqual(['alice', 'bob']);
  });

  it('drops a team whose every submission scored zero', async () => {
    // A zero total is filtered out of the ranking too, so plotting it
    // would show a team the table does not list.
    await mountPlot({
      submissions: {
        ch1: {
          alice: [{ ts: ts(T1), score: 5 }],
          zero: [{ ts: ts(T1), score: 0 }],
        },
      },
    });

    expect(seriesAt().map((s) => s.name)).toEqual(['alice']);
  });

  it('keeps a team that scored zero once but not always', async () => {
    await mountPlot({
      submissions: {
        ch1: { alice: [{ ts: ts(T1), score: 0 }, { ts: ts(T2), score: 4 }] },
      },
    });

    expect(seriesAt()).toHaveLength(1);
  });

  it('plots only the submissions that improved on the previous best', async () => {
    // The chart is a "personal best over time" line, so a worse
    // resubmission must not pull it down.
    await mountPlot({
      submissions: {
        ch1: {
          alice: [
            { ts: ts(T1), score: 5 },
            { ts: ts(T2), score: 3 },
            { ts: ts(T3), score: 9 },
          ],
        },
      },
    });

    expect(seriesAt()[0].data.map((d) => d.value[1])).toEqual([5, 9]);
  });

  it('sorts by timestamp before looking for improvements', async () => {
    await mountPlot({
      submissions: {
        ch1: {
          alice: [
            { ts: ts(T3), score: 9 },
            { ts: ts(T1), score: 5 },
          ],
        },
      },
    });

    expect(seriesAt()[0].data.map((d) => d.value)).toEqual([
      [T1.getTime(), 5],
      [T3.getTime(), 9],
    ]);
  });

  it('ignores a submission with an unparseable timestamp', async () => {
    await mountPlot({
      submissions: {
        ch1: { alice: [{ ts: 'garbage', score: 5 }, { ts: ts(T1), score: 7 }] },
      },
    });

    expect(seriesAt()[0].data).toHaveLength(1);
    expect(seriesAt()[0].data[0].value[1]).toBe(7);
  });

  it('starts the axis at the earliest plotted point', async () => {
    await mountPlot({
      submissions: { ch1: { alice: [{ ts: ts(T2), score: 5 }] } },
    });

    expect((optionAt().xAxis as { min: number }).min).toBe(T2.getTime());
  });

  it('falls back to a zero axis minimum with nothing to plot', async () => {
    await mountPlot({ submissions: {} });

    expect((optionAt().xAxis as { min: number }).min).toBe(0);
    expect(seriesAt()).toEqual([]);
  });

  it('reads only the named challenge out of the submissions', async () => {
    await mountPlot({
      challengeName: 'ch1',
      submissions: {
        ch1: { alice: [{ ts: ts(T1), score: 5 }] },
        ch2: { bob: [{ ts: ts(T1), score: 5 }] },
      },
    });

    expect(seriesAt().map((s) => s.name)).toEqual(['alice']);
  });

  describe('baseline mark line', () => {
    function withPolicies(policies: Record<string, unknown>) {
      return { A1: { ch1: { per_task_scoring_policies: policies } } };
    }

    it('sums the per-task baselines into one line', async () => {
      await mountPlot({
        assignments: withPolicies({
          correctness: { mode: 'threshold', baseline: 10 },
          performance: { mode: 'linear', baseline: 5 },
        }),
        submissions: { ch1: { alice: [{ ts: ts(T1), score: 5 }] } },
      });

      expect(seriesAt()[0].markLine?.data).toEqual([{ yAxis: 15 }]);
    });

    it('hangs the line off the first series only', async () => {
      await mountPlot({
        assignments: withPolicies({ correctness: { baseline: 10 } }),
        submissions: {
          ch1: {
            alice: [{ ts: ts(T1), score: 5 }],
            bob: [{ ts: ts(T1), score: 5 }],
          },
        },
      });

      const series = seriesAt();
      expect(series[0].markLine).toBeDefined();
      expect(series[1].markLine).toBeUndefined();
    });

    it('omits the line when no policy declares a baseline', async () => {
      await mountPlot({
        assignments: withPolicies({ correctness: { mode: 'threshold' } }),
        submissions: { ch1: { alice: [{ ts: ts(T1), score: 5 }] } },
      });

      expect(seriesAt()[0].markLine).toBeUndefined();
    });

    it('omits the line when the challenge has no policies at all', async () => {
      await mountPlot({
        assignments: { A1: { ch1: {} } },
        submissions: { ch1: { alice: [{ ts: ts(T1), score: 5 }] } },
      });

      expect(seriesAt()[0].markLine).toBeUndefined();
    });

    it('counts a baseline of zero', async () => {
      await mountPlot({
        assignments: withPolicies({ correctness: { baseline: 0 } }),
        submissions: { ch1: { alice: [{ ts: ts(T1), score: 5 }] } },
      });

      expect(seriesAt()[0].markLine?.data).toEqual([{ yAxis: 0 }]);
    });

    it('skips a non-numeric baseline', async () => {
      await mountPlot({
        assignments: withPolicies({
          a: { baseline: 'ten' },
          b: { baseline: 4 },
        }),
        submissions: { ch1: { alice: [{ ts: ts(T1), score: 5 }] } },
      });

      expect(seriesAt()[0].markLine?.data).toEqual([{ yAxis: 4 }]);
    });

    it('finds the challenge whichever assignment holds it', async () => {
      await mountPlot({
        challengeName: 'ch1',
        assignments: {
          A1: { other: { per_task_scoring_policies: { x: { baseline: 99 } } } },
          A2: { ch1: { per_task_scoring_policies: { x: { baseline: 7 } } } },
        },
        submissions: { ch1: { alice: [{ ts: ts(T1), score: 5 }] } },
      });

      expect(seriesAt()[0].markLine?.data).toEqual([{ yAxis: 7 }]);
    });
  });

  describe('tooltip', () => {
    async function formatterFor(tasks?: Record<string, number | null>) {
      await mountPlot({
        submissions: { ch1: { alice: [{ ts: ts(T1), score: 5, tasks }] } },
      });
      return tooltipFormatter();
    }

    it('shows the timestamp and the total score', async () => {
      const f = await formatterFor();

      const out = f({
        data: { value: [T1.getTime(), 5], tasks: {} },
        marker: 'M',
        seriesName: 'alice',
      });

      expect(out.split('<br/>')).toEqual([`D${T1.getTime()}`, 'Malice: 5.00']);
    });

    it('breaks the score down once there is more than one task', async () => {
      const f = await formatterFor();

      const out = f({
        data: { value: [T1.getTime(), 9], tasks: { correctness: 6, performance: 3.5 } },
        seriesName: 'alice',
      });

      expect(out).toContain('Tasks:');
      expect(out).toContain('correctness: 6.00');
      expect(out).toContain('performance: 3.50');
    });

    it('leaves the breakdown out for a single task', async () => {
      // One task means the breakdown would just repeat the total.
      const f = await formatterFor();

      const out = f({
        data: { value: [T1.getTime(), 6], tasks: { correctness: 6 } },
        seriesName: 'alice',
      });

      expect(out).not.toContain('Tasks:');
    });

    it('marks a null task score as untested rather than zero', async () => {
      const f = await formatterFor();

      const out = f({
        data: { value: [T1.getTime(), 6], tasks: { correctness: 6, performance: null } },
        seriesName: 'alice',
      });

      expect(out).toContain('performance: untested');
      expect(out).not.toContain('performance: 0.00');
    });

    it('returns an empty string when there is no point under the cursor', async () => {
      const f = await formatterFor();

      expect(f({})).toBe('');
    });
  });

  describe('lifecycle', () => {
    it('re-renders when the submissions change', async () => {
      await mountPlot({ submissions: { ch1: { alice: [{ ts: ts(T1), score: 5 }] } } });
      const before = setOption.mock.calls.length;

      await wrapper!.setProps({
        submissions: {
          ch1: { alice: [{ ts: ts(T1), score: 5 }, { ts: ts(T2), score: 8 }] },
        },
      });

      expect(setOption.mock.calls.length).toBeGreaterThan(before);
    });

    it('preserves the zoom across a poll of the same challenge', async () => {
      const { applyPreservedState } = await import(
        '../../src/components/scoreboard/chartSetup'
      );
      await mountPlot({ submissions: { ch1: { alice: [{ ts: ts(T1), score: 5 }] } } });
      vi.mocked(applyPreservedState).mockClear();

      await wrapper!.setProps({
        submissions: { ch1: { alice: [{ ts: ts(T1), score: 6 }] } },
      });

      expect(applyPreservedState).toHaveBeenCalled();
    });

    it('resets the zoom when the user switches challenge', async () => {
      // A different challenge is a different x axis and team set, so
      // carrying the old window over would show an empty chart.
      const { applyPreservedState } = await import(
        '../../src/components/scoreboard/chartSetup'
      );
      await mountPlot({
        challengeName: 'ch1',
        submissions: {
          ch1: { alice: [{ ts: ts(T1), score: 5 }] },
          ch2: { bob: [{ ts: ts(T2), score: 5 }] },
        },
      });
      vi.mocked(applyPreservedState).mockClear();

      await wrapper!.setProps({ challengeName: 'ch2' });

      expect(applyPreservedState).not.toHaveBeenCalled();
      expect(seriesAt(setOption.mock.calls.length - 1).map((s) => s.name)).toEqual(['bob']);
    });

    it('unsubscribes from theme changes on unmount', async () => {
      await mountPlot({ submissions: { ch1: { alice: [{ ts: ts(T1), score: 5 }] } } });

      wrapper!.unmount();
      wrapper = undefined;

      expect(themeListeners.size).toBe(0);
    });
  });
});
