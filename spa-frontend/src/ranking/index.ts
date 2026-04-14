import type { RankingStrategy } from './types';
import f1TimeWeighted from './f1_time_weighted';
import bestSum from './best_sum';

const registry: Record<string, RankingStrategy> = {
  [f1TimeWeighted.id]: f1TimeWeighted,
  [bestSum.id]: bestSum,
};

export function loadStrategy(modeId: string): RankingStrategy {
  return registry[modeId] ?? f1TimeWeighted;
}

export type { RankingStrategy } from './types';
