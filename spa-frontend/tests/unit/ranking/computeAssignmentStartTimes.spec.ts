import { describe, expect, it } from 'vitest';
import { computeAssignmentStartTimes, parseApiDate } from '../../../src/ranking/util';
import { apiDateOffset, challenge, DAY, HOUR } from '../../helpers/fixtures';

describe('computeAssignmentStartTimes', () => {
  it('returns an empty list for no assignments', () => {
    expect(computeAssignmentStartTimes({})).toEqual([]);
    expect(computeAssignmentStartTimes(null as never)).toEqual([]);
  });

  it('uses the earliest challenge start per assignment', () => {
    const early = apiDateOffset(-5 * DAY);
    const out = computeAssignmentStartTimes({
      Sheet1: {
        late: challenge({ start: apiDateOffset(-DAY) }),
        early: challenge({ start: early }),
      },
    });

    expect(out).toHaveLength(1);
    expect(out[0].name).toBe('Sheet1');
    expect(out[0].date.getTime()).toBe(parseApiDate(early)!.getTime());
  });

  it('omits an assignment whose every start is unparseable', () => {
    const out = computeAssignmentStartTimes({
      Broken: { a: challenge({ start: 'nope' }), b: challenge({ start: '' }) },
      Good: { g: challenge() },
    });

    // Absent entirely, rather than present with a null date.
    expect(out.map((b) => b.name)).toEqual(['Good']);
  });

  it('still includes an assignment where only some starts parse', () => {
    const good = apiDateOffset(-2 * DAY);
    const out = computeAssignmentStartTimes({
      Mixed: { bad: challenge({ start: 'nope' }), ok: challenge({ start: good }) },
    });

    expect(out).toHaveLength(1);
    expect(out[0].date.getTime()).toBe(parseApiDate(good)!.getTime());
  });

  it('sorts ascending by start', () => {
    const out = computeAssignmentStartTimes({
      Third: { c: challenge({ start: apiDateOffset(DAY) }) },
      First: { a: challenge({ start: apiDateOffset(-5 * DAY) }) },
      Second: { b: challenge({ start: apiDateOffset(-HOUR) }) },
    });

    expect(out.map((b) => b.name)).toEqual(['First', 'Second', 'Third']);
  });

  it('keeps insertion order for equal starts', () => {
    const same = apiDateOffset(-DAY);
    const out = computeAssignmentStartTimes({
      Alpha: { a: challenge({ start: same }) },
      Beta: { b: challenge({ start: same }) },
    });

    expect(out.map((b) => b.name)).toEqual(['Alpha', 'Beta']);
  });

  it('omits an assignment with no challenges at all', () => {
    expect(computeAssignmentStartTimes({ Empty: {} })).toEqual([]);
  });
});
