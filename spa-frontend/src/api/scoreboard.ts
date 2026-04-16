import { apiGet } from './client';

// Policy shape mirrors ref/core/scoring.py::apply_scoring inputs.
export type ScoringPolicy = Record<string, unknown> & { baseline?: number };

// Mirrors /api/scoreboard/config response shape.
export interface ChallengeCfg {
  start: string;
  end: string;
  per_task_scoring_policies: Record<string, ScoringPolicy>;
  max_points: number | null;
}

export type Assignments = Record<string, Record<string, ChallengeCfg>>;

export interface ScoreboardConfig {
  course_name: string;
  assignments: Assignments;
}

// One submission entry as returned by /api/scoreboard/submissions.
// `tasks` maps task_name -> transformed score; `null` means the task's
// raw score was None (bool-returning test) and should be rendered as
// "untested" rather than zero.
export interface SubmissionEntry {
  ts: string;
  score: number;
  tasks: Record<string, number | null>;
}

// Submissions: challenge -> team -> SubmissionEntry[]
export type TeamSubmissions = Record<string, SubmissionEntry[]>;
export type SubmissionsByChallenge = Record<string, TeamSubmissions>;

export function getScoreboardConfig(): Promise<ScoreboardConfig> {
  return apiGet<ScoreboardConfig>('/api/scoreboard/config');
}

export function getScoreboardSubmissions(): Promise<SubmissionsByChallenge> {
  return apiGet<SubmissionsByChallenge>('/api/scoreboard/submissions');
}

export function getScoreboardSubmissionsAdmin(): Promise<SubmissionsByChallenge> {
  return apiGet<SubmissionsByChallenge>('/api/scoreboard/submissions/admin');
}
