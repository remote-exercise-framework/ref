import { describe, expect, it } from 'vitest';
import { computeChartScoresOverTime } from '../../../src/ranking/best_sum';
import { parseApiDate } from '../../../src/ranking/util';
import { apiDateOffset, challenge, entry, HOUR } from '../../helpers/fixtures';

/**
 * The chart replays submissions in timestamp order and emits a point only
 * when a team improves its best for that challenge, so the series is
 * monotonically increasing and has no flat steps.
 */
describe('best_sum computeChartScoresOverTime', () => {
  it('returns an empty object for no submissions', () => {
    expect(computeChartScoresOverTime({}, {})).toEqual({});
    expect(computeChartScoresOverTime(null as never, null as never)).toEqual({});
  });

  it('emits a cumulative point per improvement', () => {
    const out = computeChartScoresOverTime(
      { S: { ch1: challenge() } },
      { ch1: { alice: [entry(3, -3 * HOUR), entry(7, -2 * HOUR)] } },
    );

    expect(out.alice.map((p) => p.score)).toEqual([3, 7]);
  });

  it('accumulates across challenges', () => {
    const out = computeChartScoresOverTime(
      { S: { ch1: challenge(), ch2: challenge() } },
      {
        ch1: { alice: [entry(3, -3 * HOUR)] },
        ch2: { alice: [entry(5, -2 * HOUR)] },
      },
    );

    expect(out.alice.map((p) => p.score)).toEqual([3, 8]);
  });

  it('emits no point for a non-improving resubmission', () => {
    const out = computeChartScoresOverTime(
      { S: { ch1: challenge() } },
      {
        ch1: {
          alice: [entry(7, -3 * HOUR), entry(5, -2 * HOUR), entry(7, -HOUR)],
        },
      },
    );

    // Only the first submission moves the needle.
    expect(out.alice.map((p) => p.score)).toEqual([7]);
  });

  it('emits no point for a first submission scoring zero', () => {
    // `ev.score > prev` with prev defaulting to 0 means a 0 never
    // registers. The team is then dropped for having an empty series —
    // the case most likely to regress if that comparison is loosened.
    const out = computeChartScoresOverTime(
      { S: { ch1: challenge() } },
      { ch1: { alice: [entry(0, -HOUR)] } },
    );

    expect(out).toEqual({});
  });

  it('records only the improvement delta, not the full score', () => {
    const out = computeChartScoresOverTime(
      { S: { ch1: challenge(), ch2: challenge() } },
      {
        ch1: { alice: [entry(4, -4 * HOUR), entry(6, -2 * HOUR)] },
        ch2: { alice: [entry(1, -3 * HOUR)] },
      },
    );

    // 4, then +1 (ch2) = 5, then ch1 improves by 2 = 7.
    expect(out.alice.map((p) => p.score)).toEqual([4, 5, 7]);
  });

  it('sorts events ascending by timestamp regardless of input order', () => {
    const out = computeChartScoresOverTime(
      { S: { ch1: challenge() } },
      { ch1: { alice: [entry(9, -HOUR), entry(2, -5 * HOUR)] } },
    );

    expect(out.alice.map((p) => p.score)).toEqual([2, 9]);
    expect(out.alice[0].time).toBeLessThan(out.alice[1].time);
  });

  it('reports times as epoch milliseconds matching the parsed timestamp', () => {
    const ts = apiDateOffset(-2 * HOUR);
    const out = computeChartScoresOverTime(
      { S: { ch1: challenge() } },
      { ch1: { alice: [{ ts, score: 5, tasks: {} }] } },
    );

    expect(out.alice[0].time).toBe(parseApiDate(ts)!.getTime());
  });

  it('skips entries with an unparseable timestamp', () => {
    const out = computeChartScoresOverTime(
      { S: { ch1: challenge() } },
      {
        ch1: {
          alice: [
            { ts: 'nonsense', score: 100, tasks: {} },
            entry(4, -HOUR),
          ],
        },
      },
    );

    expect(out.alice.map((p) => p.score)).toEqual([4]);
  });

  it('skips non-finite scores', () => {
    const out = computeChartScoresOverTime(
      { S: { ch1: challenge() } },
      { ch1: { alice: [entry(NaN, -2 * HOUR), entry(3, -HOUR)] } },
    );

    expect(out.alice.map((p) => p.score)).toEqual([3]);
  });

  it('ignores challenges no assignment declares', () => {
    const out = computeChartScoresOverTime(
      { S: { declared: challenge() } },
      {
        declared: { alice: [entry(2, -HOUR)] },
        undeclared: { alice: [entry(100, -2 * HOUR)] },
      },
    );

    // The undeclared challenge contributes nothing, so alice shows 2
    // rather than 102.
    expect(out.alice.map((p) => p.score)).toEqual([2]);
  });

  it('drops a team that only appears under an undeclared challenge', () => {
    // The team is seeded into the result from `submissions` before the
    // declaration filter, then deleted at the end for having no points.
    const out = computeChartScoresOverTime(
      { S: { declared: challenge() } },
      { undeclared: { ghost: [entry(42, -HOUR)] } },
    );

    expect(out).toEqual({});
    expect('ghost' in out).toBe(false);
  });

  it('keeps separate series per team', () => {
    const out = computeChartScoresOverTime(
      { S: { ch1: challenge() } },
      {
        ch1: {
          alice: [entry(5, -2 * HOUR)],
          bob: [entry(3, -3 * HOUR), entry(8, -HOUR)],
        },
      },
    );

    expect(Object.keys(out).sort()).toEqual(['alice', 'bob']);
    expect(out.alice.map((p) => p.score)).toEqual([5]);
    expect(out.bob.map((p) => p.score)).toEqual([3, 8]);
  });
});
