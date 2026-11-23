import { describe, expect, it } from 'vitest';
import { getBadges } from '../../../src/ranking/util';
import { challenge, entry } from '../../helpers/fixtures';

describe('getBadges', () => {
  it('returns an empty object when there is nothing to award', () => {
    expect(getBadges({}, {})).toEqual({});
  });

  it('awards a badge for any positive score inside a declared challenge', () => {
    const badges = getBadges(
      { Sheet1: { ch1: challenge() } },
      { ch1: { alice: [entry(5)] } },
    );

    expect(badges).toEqual({ alice: ['ch1'] });
  });

  it('gives a team with only zero scores an entry but no badge', () => {
    const badges = getBadges(
      { Sheet1: { ch1: challenge() } },
      { ch1: { alice: [entry(0)] } },
    );

    expect(badges).toEqual({ alice: [] });
  });

  it('does not double-count a challenge listed under two assignments', () => {
    const badges = getBadges(
      { Sheet1: { ch1: challenge() }, Sheet2: { ch1: challenge() } },
      { ch1: { alice: [entry(5)] } },
    );

    expect(badges.alice).toEqual(['ch1']);
  });

  it('includes a team that only appears under an undeclared challenge, with no badges', () => {
    // The second pass over `submissions` is what puts this team on the
    // board at all; it has no declared challenge so it earns nothing.
    const badges = getBadges(
      { Sheet1: { declared: challenge() } },
      { undeclared: { ghost: [entry(99)] } },
    );

    expect(badges).toEqual({ ghost: [] });
  });

  it('collects several badges per team and keeps assignment order', () => {
    const badges = getBadges(
      { Sheet1: { ch1: challenge(), ch2: challenge() } },
      {
        ch1: { alice: [entry(1)], bob: [entry(0)] },
        ch2: { alice: [entry(2)], bob: [entry(3)] },
      },
    );

    expect(badges.alice).toEqual(['ch1', 'ch2']);
    expect(badges.bob).toEqual(['ch2']);
  });

  it('awards the badge when any one of several entries scores', () => {
    const badges = getBadges(
      { Sheet1: { ch1: challenge() } },
      { ch1: { alice: [entry(0), entry(0), entry(7)] } },
    );

    expect(badges.alice).toEqual(['ch1']);
  });
});
