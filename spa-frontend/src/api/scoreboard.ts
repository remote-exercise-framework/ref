import { apiGet } from './client';

// Mirrors /api/scoreboard/config response shape.
export interface ChallengeCfg {
  start: string;
  end: string;
  scoring: Record<string, unknown> & { baseline?: number };
  max_points: number | null;
}

export type Assignments = Record<string, Record<string, ChallengeCfg>>;

export interface ScoreboardConfig {
  course_name: string;
  ranking_mode: string;
  assignments: Assignments;
}

// Submissions: challenge -> team -> [[tsStr, score], ...]
export type TeamSubmissions = Record<string, Array<[string, number]>>;
export type SubmissionsByChallenge = Record<string, TeamSubmissions>;

export function getScoreboardConfig(): Promise<ScoreboardConfig> {
  return apiGet<ScoreboardConfig>('/api/scoreboard/config');
}

export function getScoreboardSubmissions(): Promise<SubmissionsByChallenge> {
  return apiGet<SubmissionsByChallenge>('/api/scoreboard/submissions');
}
