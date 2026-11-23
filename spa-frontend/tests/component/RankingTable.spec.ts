import { afterEach, describe, expect, it } from 'vitest';
import type { VueWrapper } from '@vue/test-utils';
import RankingTable from '../../src/components/scoreboard/RankingTable.vue';
import type { Ranking } from '../../src/ranking/types';
import { mountBare } from '../helpers/mount';

describe('RankingTable', () => {
  let wrapper: VueWrapper | undefined;

  afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
  });

  function mount(props: {
    ranking: Ranking;
    badges?: Record<string, string[]>;
    hideBadges?: boolean;
  }) {
    wrapper = mountBare(RankingTable, { props });
    return wrapper;
  }

  function rows() {
    return wrapper!.findAll('[data-test="ranking-row"]');
  }

  it('shows a placeholder row when the ranking is empty', () => {
    mount({ ranking: [] });

    expect(wrapper!.find('[data-test="ranking-empty"]').text()).toContain(
      'awaiting submissions',
    );
    expect(rows()).toHaveLength(0);
  });

  it('shows the placeholder when the ranking is missing entirely', () => {
    mount({ ranking: undefined as unknown as Ranking });

    expect(wrapper!.find('[data-test="ranking-empty"]').exists()).toBe(true);
  });

  it('renders one row per team in the given order with 1-based ranks', () => {
    mount({
      ranking: [
        ['bob', 9],
        ['carol', 7],
        ['alice', 5],
      ],
    });

    expect(rows()).toHaveLength(3);
    expect(rows()[0].text()).toContain('1');
    expect(rows()[0].text()).toContain('bob');
    expect(rows()[2].text()).toContain('3');
    expect(rows()[2].text()).toContain('alice');
  });

  it('does not deduplicate or re-sort tied scores', () => {
    // Ordering is the strategy's job; the table renders what it is given.
    mount({
      ranking: [
        ['alice', 5],
        ['bob', 5],
      ],
    });

    expect(rows().map((r) => r.find('.term-team').text())).toEqual(['alice', 'bob']);
  });

  it('formats points to two decimal places', () => {
    mount({ ranking: [['alice', 7]] });

    expect(rows()[0].find('.term-points').text()).toBe('7.00');
  });

  it('formats a fractional score without rounding it away', () => {
    mount({ ranking: [['alice', 7.456]] });

    expect(rows()[0].find('.term-points').text()).toBe('7.46');
  });

  it('renders a badge image per earned badge', () => {
    mount({ ranking: [['alice', 5]], badges: { alice: ['ch1', 'ch2'] } });

    const imgs = rows()[0].findAll('img');
    expect(imgs).toHaveLength(2);
    expect(imgs[0].attributes('src')).toBe('/static/badges/ch1.svg');
    expect(imgs[0].attributes('alt')).toBe('ch1');
    expect(imgs[0].attributes('title')).toBe('ch1');
  });

  it('renders no images for a team with no badges', () => {
    mount({ ranking: [['alice', 5]], badges: {} });

    expect(rows()[0].findAll('img')).toHaveLength(0);
  });

  it('falls back to the default badge when an image fails to load', async () => {
    mount({ ranking: [['alice', 5]], badges: { alice: ['missing'] } });
    const img = rows()[0].find('img');

    await img.trigger('error');

    expect((img.element as HTMLImageElement).src).toContain('/static/badges/default.svg');
    // The handler clears itself so a failing fallback cannot loop.
    expect((img.element as HTMLImageElement).onerror).toBeNull();
  });

  describe('hideBadges', () => {
    it('drops the badge column from the header and the rows', () => {
      mount({ ranking: [['alice', 5]], badges: { alice: ['ch1'] }, hideBadges: true });

      expect(wrapper!.findAll('th')).toHaveLength(3);
      expect(wrapper!.text()).not.toContain('Badges');
      expect(rows()[0].findAll('img')).toHaveLength(0);
    });

    it('keeps the badge column by default', () => {
      mount({ ranking: [['alice', 5]] });

      expect(wrapper!.findAll('th')).toHaveLength(4);
      expect(wrapper!.text()).toContain('Badges');
    });

    it('spans the placeholder row across the visible columns', () => {
      mount({ ranking: [], hideBadges: true });
      expect(wrapper!.find('[data-test="ranking-empty"] td').attributes('colspan')).toBe('3');

      wrapper!.unmount();
      mount({ ranking: [] });
      expect(wrapper!.find('[data-test="ranking-empty"] td').attributes('colspan')).toBe('4');
    });
  });
});
