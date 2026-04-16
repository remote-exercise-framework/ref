// Ranking-strategy interface — mirrors the existing JS strategy modules.

import type { Assignments, SubmissionsByChallenge } from '../api/scoreboard';

export type Ranking = Array<[string, number]>;
export type ScoresOverTime = Record<
  string,
  Array<{ time: number; score: number }>
>;

export interface RankingStrategy {
  id: string;
  label: string;
  getRanking(
    assignments: Assignments,
    submissions: SubmissionsByChallenge,
  ): Ranking;
  computeChartScoresOverTime(
    assignments: Assignments,
    submissions: SubmissionsByChallenge,
  ): ScoresOverTime;
}
