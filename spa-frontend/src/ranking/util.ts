// Strategy-agnostic helpers for scoreboard data.
// Ported from the legacy webapp/ref/static/js/utils.js.

import type {
  Assignments,
  ChallengeCfg,
  SubmissionsByChallenge,
} from '../api/scoreboard';

// The Flask API emits dates as "DD/MM/YYYY HH:MM:SS" via
// ref.core.util.datetime_to_string.
export function parseApiDate(ts: string | null | undefined): Date | null {
  if (!ts || typeof ts !== 'string') return null;
  const [datePart, timePart] = ts.trim().split(' ');
  if (!datePart || !timePart) return null;
  const [dd, mm, yyyy] = datePart.split('/').map(Number);
  const [HH, MM, SS] = timePart.split(':').map(Number);
  const d = new Date(yyyy, mm - 1, dd, HH, MM, SS, 0);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function hoursSince(ts: string | null | undefined): string {
  const when = parseApiDate(ts);
  if (!when) return '–';
  const ms = Date.now() - when.getTime();
  if (ms < 0) return '0h';
  return `${Math.floor(ms / 3600000)}h`;
}

// Highest transformed score per (challenge, team). Returns
// { challenge: [team, score, tsStr] } keyed by best score.
export type Highscores = Record<string, [string, number, string]>;

export function getHighscores(
  _assignments: Assignments,
  submissions: SubmissionsByChallenge,
): Highscores {
  const out: Highscores = {};
  for (const challenge of Object.keys(submissions || {})) {
    let best: { team: string; score: number; ts: Date; tsStr: string } | null =
      null;
    const teams = submissions[challenge] || {};
    for (const team of Object.keys(teams)) {
      for (const [tsStr, rawScore] of teams[team] || []) {
        const score = Number(rawScore);
        const ts = parseApiDate(tsStr);
        if (!ts || Number.isNaN(score)) continue;
        if (
          !best ||
          score > best.score ||
          (score === best.score && ts < best.ts)
        ) {
          best = { team, score, ts, tsStr };
        }
      }
    }
    if (best) out[challenge] = [best.team, best.score, best.tsStr];
  }
  return out;
}

// A team earns the badge for a challenge iff they earned any transformed
// points inside the challenge window.
export type Badges = Record<string, string[]>;

export function getBadges(
  assignments: Assignments,
  submissions: SubmissionsByChallenge,
): Badges {
  const out: Badges = {};
  for (const challenges of Object.values(assignments || {})) {
    for (const [challenge, cfg] of Object.entries(challenges || {})) {
      const cStart = parseApiDate(cfg.start);
      const cEnd = parseApiDate(cfg.end);
      if (!cStart || !cEnd) continue;
      const teams = (submissions && submissions[challenge]) || {};
      for (const team of Object.keys(teams)) {
        let earned = false;
        for (const [tsStr, rawScore] of teams[team] || []) {
          const ts = parseApiDate(tsStr);
          if (!ts || ts < cStart || ts > cEnd) continue;
          if (Number(rawScore) > 0) {
            earned = true;
            break;
          }
        }
        if (!out[team]) out[team] = [];
        if (earned && !out[team].includes(challenge)) out[team].push(challenge);
      }
    }
  }
  for (const teams of Object.values(submissions || {})) {
    for (const team of Object.keys(teams || {})) {
      if (!out[team]) out[team] = [];
    }
  }
  return out;
}

// Assignment whose challenges are currently submittable (start <= now <=
// end). If multiple are active, pick the one whose earliest start is
// latest so the newest open assignment wins.
export function getActiveAssignmentName(
  assignments: Assignments,
): string | null {
  const now = new Date();
  let best: string | null = null;
  let bestStart: Date | null = null;
  for (const [name, challenges] of Object.entries(assignments || {})) {
    let anyActive = false;
    let earliestStart: Date | null = null;
    for (const ch of Object.values(challenges || {}) as ChallengeCfg[]) {
      const s = parseApiDate(ch.start);
      const e = parseApiDate(ch.end);
      if (!s || !e) continue;
      if (s <= now && now <= e) anyActive = true;
      if (!earliestStart || s < earliestStart) earliestStart = s;
    }
    if (anyActive && earliestStart && (!bestStart || earliestStart > bestStart)) {
      best = name;
      bestStart = earliestStart;
    }
  }
  return best;
}

export function computeAssignmentStartTimes(
  assignments: Assignments,
): Date[] {
  const times: Date[] = [];
  for (const challenges of Object.values(assignments || {})) {
    let earliest: Date | null = null;
    for (const ch of Object.values(challenges || {}) as ChallengeCfg[]) {
      const s = parseApiDate(ch.start);
      if (s && (!earliest || s < earliest)) earliest = s;
    }
    if (earliest) times.push(earliest);
  }
  times.sort((a, b) => a.getTime() - b.getTime());
  return times;
}
