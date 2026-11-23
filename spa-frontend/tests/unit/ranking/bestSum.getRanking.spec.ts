import { describe, expect, it } from 'vitest';
import { getRanking } from '../../../src/ranking/best_sum';
import { getHighscores } from '../../../src/ranking/util';
import { challenge, entry } from '../../helpers/fixtures';

describe('best_sum getRanking', () => {
  it('returns an empty ranking for no submissions', () => {
    expect(getRanking({}, {})).toEqual([]);
    expect(getRanking(null as never, null as never)).toEqual([]);
  });

  it('skips a challenge that no assignment declares', () => {
    const ranking = getRanking(
      { Sheet1: { declared: challenge() } },
      { undeclared: { alice: [entry(50)] } },
    );

    expect(ranking).toEqual([]);
  });

  it('takes the best score per challenge, then sums across challenges', () => {
    const ranking = getRanking(
      { Sheet1: { ch1: challenge(), ch2: challenge() } },
      {
        ch1: { alice: [entry(3), entry(7), entry(5)] },
        ch2: { alice: [entry(10)] },
      },
    );

    expect(ranking).toEqual([['alice', 17]]);
  });

  it('sorts descending by total', () => {
    const ranking = getRanking(
      { Sheet1: { ch1: challenge() } },
      { ch1: { alice: [entry(5)], bob: [entry(9)], carol: [entry(7)] } },
    );

    expect(ranking).toEqual([
      ['bob', 9],
      ['carol', 7],
      ['alice', 5],
    ]);
  });

  it('keeps insertion order for tied totals', () => {
    const ranking = getRanking(
      { Sheet1: { ch1: challenge() } },
      { ch1: { alice: [entry(5)], bob: [entry(5)] } },
    );

    expect(ranking).toEqual([
      ['alice', 5],
      ['bob', 5],
    ]);
  });

  it('counts null and empty-string scores as a real zero', () => {
    // Number(null) and Number('') are both 0, which is finite, so these
    // entries are kept and contribute 0 rather than being skipped. The
    // team is then filtered out for totalling zero — but a second
    // challenge with real points proves the zero was counted, not dropped.
    const ranking = getRanking(
      { Sheet1: { ch1: challenge(), ch2: challenge() } },
      {
        ch1: { alice: [entry(null)], bob: [entry('' as unknown as number)] },
        ch2: { alice: [entry(4)], bob: [entry(4)] },
      },
    );

    expect(ranking).toEqual([
      ['alice', 4],
      ['bob', 4],
    ]);
  });

  it('drops non-finite scores', () => {
    const ranking = getRanking(
      { Sheet1: { ch1: challenge(), ch2: challenge() } },
      {
        ch1: {
          alice: [entry(NaN), entry(Infinity), entry(undefined), entry('x' as never)],
        },
        ch2: { alice: [entry(6)] },
      },
    );

    // Only the ch2 entry survives.
    expect(ranking).toEqual([['alice', 6]]);
  });

  it('filters out a team whose total is exactly zero', () => {
    const ranking = getRanking(
      { Sheet1: { ch1: challenge() } },
      { ch1: { alice: [entry(0)] } },
    );

    expect(ranking).toEqual([]);
  });

  it('filters out a team whose total is negative', () => {
    const ranking = getRanking(
      { Sheet1: { ch1: challenge() } },
      { ch1: { alice: [entry(-5)] } },
    );

    expect(ranking).toEqual([]);
  });

  it('keeps a team whose negative challenge is offset into the positive', () => {
    const ranking = getRanking(
      { Sheet1: { ch1: challenge(), ch2: challenge() } },
      { ch1: { alice: [entry(-5)] }, ch2: { alice: [entry(8)] } },
    );

    expect(ranking).toEqual([['alice', 3]]);
  });

  it('diverges from getHighscores on undeclared challenges', () => {
    // Same input, opposite treatment: getRanking honours the assignment
    // declaration, getHighscores ignores its first argument entirely. The
    // divergence is pinned here so reviving the dead helper cannot
    // silently change the board.
    const assignments = { Sheet1: { declared: challenge() } };
    const subs = { undeclared: { ghost: [entry(42)] } };

    expect(getRanking(assignments, subs)).toEqual([]);
    expect(getHighscores(assignments, subs).undeclared[0]).toBe('ghost');
  });
});
