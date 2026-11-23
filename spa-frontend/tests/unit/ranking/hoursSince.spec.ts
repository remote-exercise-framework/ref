import { afterEach, describe, expect, it, vi } from 'vitest';
import { hoursSince } from '../../../src/ranking/util';
import { apiDate, HOUR } from '../../helpers/fixtures';

describe('hoursSince', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  function at(now: Date) {
    vi.useFakeTimers();
    vi.setSystemTime(now);
  }

  it('returns an en dash for an unparseable timestamp', () => {
    // U+2013, not a hyphen — written as an escape so the distinction
    // survives an editor that normalises dashes.
    expect(hoursSince('nonsense')).toBe('–');
    expect(hoursSince(null)).toBe('–');
    expect(hoursSince(undefined)).toBe('–');
    expect(hoursSince('')).toBe('–');
  });

  it('reports 0h for a timestamp in the future', () => {
    const now = new Date(2024, 5, 1, 12, 0, 0);
    at(now);

    expect(hoursSince(apiDate(new Date(now.getTime() + 5 * HOUR)))).toBe('0h');
  });

  it('reports 0h for the current instant', () => {
    const now = new Date(2024, 5, 1, 12, 0, 0);
    at(now);

    expect(hoursSince(apiDate(now))).toBe('0h');
  });

  it('floors partial hours', () => {
    const now = new Date(2024, 5, 1, 12, 0, 0);
    at(now);
    const almostTwo = new Date(now.getTime() - (HOUR + 59 * 60_000));

    expect(hoursSince(apiDate(almostTwo))).toBe('1h');
  });

  it('keeps counting in hours past a day rather than rolling over', () => {
    const now = new Date(2024, 5, 2, 13, 0, 0);
    at(now);
    const earlier = new Date(now.getTime() - 25 * HOUR);

    expect(hoursSince(apiDate(earlier))).toBe('25h');
  });
});
