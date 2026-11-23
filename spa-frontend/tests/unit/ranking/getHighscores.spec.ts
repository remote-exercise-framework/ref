import { describe, expect, it } from 'vitest';
import { getHighscores } from '../../../src/ranking/util';
import { apiDateOffset, challenge, entry, HOUR } from '../../helpers/fixtures';

/**
 * getHighscores has no live consumer in the SPA, but it is pure and short,
 * so it is covered here to document its intent — and specifically its two
 * divergences from getRanking, which a future revival could otherwise
 * carry into the board unnoticed.
 */
describe('getHighscores', () => {
  it('returns an empty object for no submissions', () => {
    expect(getHighscores({}, {})).toEqual({});
    expect(getHighscores(null as never, null as never)).toEqual({});
  });

  it('ignores its assignments argument and includes undeclared challenges', () => {
    const out = getHighscores({}, { anything: { alice: [entry(5)] } });

    expect(out.anything).toEqual(['alice', 5, expect.any(String)]);
  });

  it('reports the single best entry per challenge across all teams', () => {
    const out = getHighscores(
      { S: { ch1: challenge() } },
      { ch1: { alice: [entry(5)], bob: [entry(9)], carol: [entry(7)] } },
    );

    expect(out.ch1[0]).toBe('bob');
    expect(out.ch1[1]).toBe(9);
  });

  it('breaks a tie in favour of the earlier submission', () => {
    const out = getHighscores(
      { S: { ch1: challenge() } },
      {
        ch1: {
          late: [entry(5, -HOUR)],
          early: [entry(5, -5 * HOUR)],
        },
      },
    );

    expect(out.ch1[0]).toBe('early');
  });

  it('returns the raw timestamp string, not a Date', () => {
    const ts = apiDateOffset(-2 * HOUR);
    const out = getHighscores({}, { ch1: { alice: [{ ts, score: 5, tasks: {} }] } });

    expect(out.ch1[2]).toBe(ts);
    expect(typeof out.ch1[2]).toBe('string');
  });

  it('skips entries with an unparseable timestamp or a NaN score', () => {
    const out = getHighscores(
      {},
      {
        ch1: {
          alice: [
            { ts: 'nonsense', score: 100, tasks: {} },
            entry(NaN, -HOUR),
            entry(4, -2 * HOUR),
          ],
        },
      },
    );

    expect(out.ch1[1]).toBe(4);
  });

  it('omits a challenge where every entry was skipped', () => {
    const out = getHighscores({}, { ch1: { alice: [{ ts: 'bad', score: 1, tasks: {} }] } });

    expect('ch1' in out).toBe(false);
  });

  it('keeps a zero-scoring best, unlike getRanking', () => {
    // getRanking filters totals of 0 out; this does not.
    const out = getHighscores({}, { ch1: { alice: [entry(0)] } });

    expect(out.ch1[1]).toBe(0);
  });
});
