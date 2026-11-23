import { describe, expect, it } from 'vitest';
import { strategy } from '../../../src/ranking';
import bestSum, {
  computeChartScoresOverTime,
  getRanking,
  id,
  label,
} from '../../../src/ranking/best_sum';

/**
 * The scoreboard reaches its ranking algorithm only through this re-export,
 * so a mis-wired strategy swap would change every placement silently.
 */
describe('ranking strategy wiring', () => {
  it('re-exports the best_sum strategy object itself', () => {
    expect(strategy).toBe(bestSum);
  });

  it('exposes the same function identities as best_sum', () => {
    expect(strategy.getRanking).toBe(getRanking);
    expect(strategy.computeChartScoresOverTime).toBe(computeChartScoresOverTime);
  });

  it('carries the strategy id and label', () => {
    expect(strategy.id).toBe(id);
    expect(strategy.label).toBe(label);
    expect(strategy.id).toBe('best_sum');
  });
});
