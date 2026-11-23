import { describe, expect, it } from 'vitest';
import { getActiveAssignmentName } from '../../../src/ranking/util';
import {
  apiDateOffset,
  challenge,
  DAY,
  futureChallenge,
  HOUR,
  pastChallenge,
} from '../../helpers/fixtures';

/**
 * Two-phase selection: an assignment with a currently-open challenge wins
 * over any upcoming one, and among equals the soonest end (resp. soonest
 * start) wins.
 */
describe('getActiveAssignmentName', () => {
  it('returns null for no assignments', () => {
    expect(getActiveAssignmentName({})).toBeNull();
    expect(getActiveAssignmentName(null as never)).toBeNull();
  });

  it('returns null when an assignment has no challenges', () => {
    expect(getActiveAssignmentName({ Sheet1: {} })).toBeNull();
  });

  it('picks the assignment holding the only active challenge', () => {
    expect(
      getActiveAssignmentName({
        Sheet1: { ch1: pastChallenge() },
        Sheet2: { ch2: challenge() },
      }),
    ).toBe('Sheet2');
  });

  it('prefers the active assignment whose challenge ends soonest', () => {
    expect(
      getActiveAssignmentName({
        Later: { l: challenge({ end: apiDateOffset(5 * DAY) }) },
        Sooner: { s: challenge({ end: apiDateOffset(2 * HOUR) }) },
      }),
    ).toBe('Sooner');
  });

  it('is not decided by insertion order', () => {
    const later = { l: challenge({ end: apiDateOffset(5 * DAY) }) };
    const sooner = { s: challenge({ end: apiDateOffset(2 * HOUR) }) };

    expect(getActiveAssignmentName({ Sooner: sooner, Later: later })).toBe('Sooner');
    expect(getActiveAssignmentName({ Later: later, Sooner: sooner })).toBe('Sooner');
  });

  it('returns null when every challenge is wholly in the past', () => {
    expect(
      getActiveAssignmentName({ Sheet1: { a: pastChallenge(), b: pastChallenge() } }),
    ).toBeNull();
  });

  it('falls back to the upcoming assignment with the nearest start', () => {
    expect(
      getActiveAssignmentName({
        Far: { f: futureChallenge(10 * DAY) },
        Near: { n: futureChallenge(2 * HOUR) },
      }),
    ).toBe('Near');
  });

  it('prefers any active assignment over a sooner-starting upcoming one', () => {
    expect(
      getActiveAssignmentName({
        ActiveButEndsLate: { x: challenge({ end: apiDateOffset(30 * DAY) }) },
        StartsVerySoon: { y: futureChallenge(HOUR) },
      }),
    ).toBe('ActiveButEndsLate');
  });

  it('excludes an assignment from the upcoming slot when it is already active', () => {
    // Sheet1 has both an open challenge and a future one. It must not
    // compete for the upcoming slot, so Sheet2 — upcoming and sooner —
    // still loses to Sheet1's active challenge.
    expect(
      getActiveAssignmentName({
        Sheet1: {
          open: challenge({ end: apiDateOffset(20 * DAY) }),
          later: futureChallenge(10 * DAY),
        },
        Sheet2: { soon: futureChallenge(HOUR) },
      }),
    ).toBe('Sheet1');
  });

  it('skips challenges with unparseable dates without throwing', () => {
    expect(
      getActiveAssignmentName({
        Broken: { b: challenge({ start: 'nonsense', end: 'also nonsense' }) },
        Good: { g: challenge() },
      }),
    ).toBe('Good');
  });

  it('ignores a challenge whose end is missing even when the start parses', () => {
    expect(getActiveAssignmentName({ Half: { h: challenge({ end: '' }) } })).toBeNull();
  });
});
