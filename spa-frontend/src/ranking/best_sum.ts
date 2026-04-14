// Sum-of-best-per-challenge ranking strategy.
//
// Each team's score for a challenge is their highest in-window
// submission score; the ranking score is the sum across challenges.

import type {
  Assignments,
  SubmissionsByChallenge,
} from '../api/scoreboard';
import { parseApiDate } from './util';
import type { Ranking, RankingStrategy, ScoresOverTime } from './types';

export const id = 'best_sum';
export const label = 'Sum of best per challenge';

function bestPerChallenge(
  assignments: Assignments,
  submissions: SubmissionsByChallenge,
): Record<string, Record<string, number>> {
  const best: Record<string, Record<string, number>> = {};
  for (const challenges of Object.values(assignments || {})) {
    for (const [name, cfg] of Object.entries(challenges || {})) {
      const cStart = parseApiDate(cfg.start);
      const cEnd = parseApiDate(cfg.end);
      if (!cStart || !cEnd) continue;
      const teams = (submissions && submissions[name]) || {};
      if (!best[name]) best[name] = {};
      for (const team of Object.keys(teams)) {
        for (const entry of teams[team] || []) {
          const ts = parseApiDate(entry.ts);
          if (!ts || ts < cStart || ts > cEnd) continue;
          const score = Number(entry.score);
          if (!Number.isFinite(score)) continue;
          if (!(team in best[name]) || score > best[name][team]) {
            best[name][team] = score;
          }
        }
      }
    }
  }
  return best;
}

export function getRanking(
  assignments: Assignments,
  submissions: SubmissionsByChallenge,
): Ranking {
  const best = bestPerChallenge(assignments, submissions);
  const totals: Record<string, number> = {};
  for (const teams of Object.values(best)) {
    for (const [team, score] of Object.entries(teams)) {
      totals[team] = (totals[team] || 0) + score;
    }
  }
  return Object.entries(totals).sort((a, b) => b[1] - a[1]);
}

export function computeChartScoresOverTime(
  assignments: Assignments,
  submissions: SubmissionsByChallenge,
): ScoresOverTime {
  const teamSet = new Set<string>();
  for (const teams of Object.values(submissions || {})) {
    for (const team of Object.keys(teams)) teamSet.add(team);
  }
  const out: ScoresOverTime = {};
  for (const team of teamSet) out[team] = [];

  interface Ev {
    ts: Date;
    team: string;
    challenge: string;
    score: number;
  }

  const events: Ev[] = [];
  for (const challenges of Object.values(assignments || {})) {
    for (const [name, cfg] of Object.entries(challenges || {})) {
      const cStart = parseApiDate(cfg.start);
      const cEnd = parseApiDate(cfg.end);
      if (!cStart || !cEnd) continue;
      const teams = (submissions && submissions[name]) || {};
      for (const team of Object.keys(teams)) {
        for (const entry of teams[team] || []) {
          const ts = parseApiDate(entry.ts);
          if (!ts || ts < cStart || ts > cEnd) continue;
          const score = Number(entry.score);
          if (!Number.isFinite(score)) continue;
          events.push({ ts, team, challenge: name, score });
        }
      }
    }
  }
  events.sort((a, b) => a.ts.getTime() - b.ts.getTime());

  const bestPer: Record<string, Record<string, number>> = {};
  const totals: Record<string, number> = {};
  for (const team of teamSet) {
    bestPer[team] = {};
    totals[team] = 0;
  }

  for (const ev of events) {
    const prev = bestPer[ev.team][ev.challenge] ?? 0;
    if (ev.score > prev) {
      totals[ev.team] += ev.score - prev;
      bestPer[ev.team][ev.challenge] = ev.score;
    }
    out[ev.team].push({ time: ev.ts.getTime(), score: totals[ev.team] });
  }

  const nowMs = Date.now();
  for (const team of teamSet) {
    if (out[team].length === 0) out[team].push({ time: nowMs, score: 0 });
  }
  return out;
}

const strategy: RankingStrategy = {
  id,
  label,
  getRanking,
  computeChartScoresOverTime,
};
export default strategy;
