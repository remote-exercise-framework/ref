import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { VueWrapper } from '@vue/test-utils';
import Countdown from '../../src/components/scoreboard/Countdown.vue';
import { apiDate } from '../helpers/fixtures';
import { mountBare } from '../helpers/mount';

const NOW = new Date(2024, 5, 1, 12, 0, 0);
const HOUR = 3600_000;
const DAY = 24 * HOUR;

describe('Countdown', () => {
  let wrapper: VueWrapper | undefined;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
    vi.useRealTimers();
  });

  function mount(startOffset: number, endOffset: number) {
    wrapper = mountBare(Countdown, {
      props: {
        start: apiDate(new Date(NOW.getTime() + startOffset)),
        end: apiDate(new Date(NOW.getTime() + endOffset)),
      },
    });
    return wrapper;
  }

  function label() {
    return wrapper!.find('.term-countdown-label').text();
  }

  function fillWidth() {
    return wrapper!.find('.term-countdown-fill').attributes('style') ?? '';
  }

  it('shows hours, minutes and seconds within a day', () => {
    mount(-HOUR, 2 * HOUR + 3 * 60_000 + 4000);

    expect(label()).toBe('Remaining: 02h 03m 04s');
  });

  it('prefixes a day count once more than 24 hours remain', () => {
    mount(-HOUR, 2 * DAY + 3 * HOUR);

    expect(label()).toBe('Remaining: 2d 03h 00m 00s');
  });

  it('zero-pads each component', () => {
    mount(-HOUR, 5 * 60_000 + 9000);

    expect(label()).toBe('Remaining: 00h 05m 09s');
  });

  it('clamps to zero once the deadline has passed', () => {
    mount(-2 * DAY, -HOUR);

    expect(label()).toBe('Remaining: 00h 00m 00s');
    expect(fillWidth()).toContain('100%');
  });

  it('shows an en dash when the dates are unparseable', () => {
    wrapper = mountBare(Countdown, { props: { start: 'nope', end: 'also nope' } });

    expect(label()).toBe('Remaining: –');
    expect(fillWidth()).toContain('0%');
  });

  it('fills the bar in proportion to elapsed time', () => {
    // Half the window gone.
    mount(-5 * HOUR, 5 * HOUR);

    expect(fillWidth()).toContain('50%');
  });

  it('keeps the fill at zero before the window opens', () => {
    mount(HOUR, 2 * HOUR);

    expect(fillWidth()).toContain('0%');
  });

  it('ticks down as time advances', async () => {
    mount(-HOUR, 10_000);
    expect(label()).toBe('Remaining: 00h 00m 10s');

    vi.advanceTimersByTime(3000);
    await wrapper!.vm.$nextTick();

    expect(label()).toBe('Remaining: 00h 00m 07s');
  });

  it('stops its interval on unmount', async () => {
    const clear = vi.spyOn(window, 'clearInterval');
    mount(-HOUR, HOUR);

    wrapper!.unmount();
    wrapper = undefined;

    expect(clear).toHaveBeenCalled();
  });
});
