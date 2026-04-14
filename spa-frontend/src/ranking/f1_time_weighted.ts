// Formula-1 style time-weighted ranking.
//
// Ported verbatim from webapp/ref/static/js/ranking/f1_time_weighted.js.

import type {
  Assignments,
  SubmissionsByChallenge,
  TeamSubmissions,
} from '../api/scoreboard';
import { parseApiDate } from './util';
import type { Ranking, RankingStrategy, ScoresOverTime } from './types';

export const id = 'f1_time_weighted';
export const label = 'Formula 1 (time-weighted)';

const RANK_POINTS = Array.from({ length: 10 }, (_, i) => 1 / (i + 1));

interface Event {
  ts: Date;
  team: string;
  score: number;
}

function buildTimeline(challengeTeams: TeamSubmissions): Event[] {
  const events: Event[] = [];
  for (const team of Object.keys(challengeTeams || {})) {
    for (const [tsStr, score] of challengeTeams[team] || []) {
      const ts = parseApiDate(tsStr);
      if (!ts) continue;
      events.push({ ts, team, score: Number(score) });
    }
  }
  events.sort((a, b) => a.ts.getTime() - b.ts.getTime());
  return events;
}

function calcChallengeTicks(
  challengeTeams: TeamSubmissions,
  start: Date,
  end: Date,
): Record<string, number> {
  const teamTicks: Record<string, number> = {};
  for (const team of Object.keys(challengeTeams || {})) teamTicks[team] = 0;
  const events = buildTimeline(challengeTeams);
  if (events.length === 0) return teamTicks;

  const bestSoFar: Record<string, number> = {};
  for (const ev of events) {
    if (ev.ts <= start) {
      if (!(ev.team in bestSoFar) || ev.score > bestSoFar[ev.team]) {
        bestSoFar[ev.team] = ev.score;
      }
    } else break;
  }

  function getRankingArr() {
    return Object.entries(bestSoFar)
      .map(([team, score]) => ({ team, score }))
      .sort((a, b) => b.score - a.score)
      .slice(0, RANK_POINTS.length);
  }

  let ranking = getRankingArr();
  let lastTs = start;

  function accrue(toTs: Date) {
    const seconds = Math.max(0, (toTs.getTime() - lastTs.getTime()) / 1000);
    if (seconds > 0) {
      for (let i = 0; i < ranking.length; i++) {
        teamTicks[ranking[i].team] += seconds * RANK_POINTS[i];
      }
    }
    lastTs = toTs;
  }

  for (const ev of events) {
    if (ev.ts < start) continue;
    if (ev.ts > end) break;
    accrue(ev.ts);
    if (!(ev.team in bestSoFar) || ev.score > bestSoFar[ev.team]) {
      bestSoFar[ev.team] = ev.score;
      ranking = getRankingArr();
    }
  }
  accrue(end);
  return teamTicks;
}

function calcAllTicks(
  assignments: Assignments,
  submissions: SubmissionsByChallenge,
  globalEnd: Date | null = null,
): Record<string, number> {
  const ticks: Record<string, number> = {};
  const cap = globalEnd || new Date();
  for (const challenges of Object.values(assignments || {})) {
    for (const [challenge, cfg] of Object.entries(challenges || {})) {
      const cStart = parseApiDate(cfg.start);
      const cEnd = parseApiDate(cfg.end);
      if (!cStart || !cEnd) continue;
      const end = cEnd < cap ? cEnd : cap;
      if (cStart >= end) continue;
      const subs = (submissions && submissions[challenge]) || {};
      const challTicks = calcChallengeTicks(subs, cStart, end);
      for (const [team, t] of Object.entries(challTicks)) {
        ticks[team] = (ticks[team] || 0) + t;
      }
    }
  }
  return ticks;
}

export function getRanking(
  assignments: Assignments,
  submissions: SubmissionsByChallenge,
): Ranking {
  const ticks = calcAllTicks(assignments, submissions);
  const ranking: Ranking = Object.entries(ticks).map(([team, t]) => [
    team,
    t / 3600,
  ]);
  ranking.sort((a, b) => b[1] - a[1]);
  return ranking;
}

export function computeChartScoresOverTime(
  assignments: Assignments,
  submissions: SubmissionsByChallenge,
  noIntervals = 40,
): ScoresOverTime {
  const teamSet = new Set<string>();
  for (const teams of Object.values(submissions || {})) {
    for (const team of Object.keys(teams)) teamSet.add(team);
  }
  if (teamSet.size === 0) return {};

  let minStart: Date | null = null;
  let maxEnd: Date | null = null;
  for (const challenges of Object.values(assignments || {})) {
    for (const cfg of Object.values(challenges || {})) {
      const s = parseApiDate(cfg.start);
      const e = parseApiDate(cfg.end);
      if (!s || !e) continue;
      if (!minStart || s < minStart) minStart = s;
      if (!maxEnd || e > maxEnd) maxEnd = e;
    }
  }
  if (!minStart || !maxEnd || minStart >= maxEnd) {
    const nowMs = Date.now();
    const out: ScoresOverTime = {};
    for (const team of teamSet) out[team] = [{ time: nowMs, score: 0 }];
    return out;
  }

  const now = new Date();
  const chartEnd = now < maxEnd ? now : maxEnd;
  const step = (chartEnd.getTime() - minStart.getTime()) / noIntervals;
  if (step <= 0) {
    const out: ScoresOverTime = {};
    for (const team of teamSet) out[team] = [{ time: minStart.getTime(), score: 0 }];
    return out;
  }

  const out: ScoresOverTime = {};
  for (const team of teamSet) out[team] = [];
  for (let i = 0; i <= noIntervals; i++) {
    const cursor = new Date(minStart.getTime() + i * step);
    const ticks = calcAllTicks(assignments, submissions, cursor);
    for (const team of teamSet) {
      out[team].push({
        time: cursor.getTime(),
        score: (ticks[team] || 0) / 3600,
      });
    }
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
