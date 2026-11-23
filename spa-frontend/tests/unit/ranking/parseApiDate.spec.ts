import { describe, expect, it } from 'vitest';
import { parseApiDate } from '../../../src/ranking/util';

/**
 * parseApiDate consumes "DD/MM/YYYY HH:MM:SS" as emitted by
 * ref.core.util.datetime_to_string, and builds the Date in LOCAL time.
 * Tests run under TZ=UTC (vitest.config.ts), so assertions use the local
 * getters rather than toISOString().
 */
describe('parseApiDate', () => {
  it('parses a well-formed API timestamp', () => {
    const d = parseApiDate('01/02/2024 03:04:05');

    expect(d).not.toBeNull();
    expect(d!.getFullYear()).toBe(2024);
    expect(d!.getMonth()).toBe(1); // February, zero-based
    expect(d!.getDate()).toBe(1);
    expect(d!.getHours()).toBe(3);
    expect(d!.getMinutes()).toBe(4);
    expect(d!.getSeconds()).toBe(5);
  });

  it('reads the day first, not the month', () => {
    // The distinguishing case: 13 cannot be a month, so a parser that got
    // the order wrong would produce an invalid date or roll the year.
    const d = parseApiDate('13/07/2024 00:00:00');

    expect(d!.getDate()).toBe(13);
    expect(d!.getMonth()).toBe(6);
  });

  it.each([
    ['null', null],
    ['undefined', undefined],
    ['an empty string', ''],
  ])('returns null for %s', (_label, input) => {
    expect(parseApiDate(input as string | null | undefined)).toBeNull();
  });

  it.each([
    ['a number', 1234],
    ['an object', { ts: '01/02/2024 03:04:05' }],
    ['a Date', new Date()],
  ])('returns null for %s (non-string input)', (_label, input) => {
    expect(parseApiDate(input as unknown as string)).toBeNull();
  });

  it('returns null when the time part is missing', () => {
    expect(parseApiDate('01/02/2024')).toBeNull();
  });

  it('returns null for an ISO timestamp', () => {
    // The API never emits ISO, and this parser cannot read it.
    expect(parseApiDate('2024-02-01T03:04:05Z')).toBeNull();
  });

  it('returns null when two spaces separate date and time', () => {
    // split(' ') yields ['01/02/2024', '', '03:04:05'], so timePart is the
    // empty string and the guard rejects it. Subtle enough to pin.
    expect(parseApiDate('01/02/2024  03:04:05')).toBeNull();
  });

  it('tolerates surrounding whitespace', () => {
    // The implementation trims before splitting.
    const d = parseApiDate('  01/02/2024 03:04:05  ');

    expect(d).not.toBeNull();
    expect(d!.getDate()).toBe(1);
  });

  it('builds a Date from a partial time, filling missing fields with NaN-free zeros', () => {
    // "03:04" leaves SS undefined -> new Date(..., undefined) is invalid.
    expect(parseApiDate('01/02/2024 03:04')).toBeNull();
  });

  it('does not validate ranges and lets the Date constructor roll over', () => {
    // Documents deliberate leniency rather than asserting it is desirable:
    // 32/13/2024 25:61:61 becomes 2025-02-02T02:02:01 local.
    const d = parseApiDate('32/13/2024 25:61:61');

    expect(d).not.toBeNull();
    expect(d!.getFullYear()).toBe(2025);
    expect(d!.getMonth()).toBe(1);
    expect(d!.getDate()).toBe(2);
    expect(d!.getHours()).toBe(2);
    expect(d!.getMinutes()).toBe(2);
    expect(d!.getSeconds()).toBe(1);
  });

  it('maps two-digit years into the 20th century', () => {
    // new Date(99, ...) means 1999, not 2099 — a trap if the API ever
    // shortened its year format.
    expect(parseApiDate('01/01/99 00:00:00')!.getFullYear()).toBe(1999);
    expect(parseApiDate('01/01/00 00:00:00')!.getFullYear()).toBe(1900);
  });

  it('returns null when a component is not numeric', () => {
    expect(parseApiDate('aa/bb/cccc 00:00:00')).toBeNull();
  });
});
