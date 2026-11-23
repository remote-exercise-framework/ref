import type {
  Assignments,
  ChallengeCfg,
  ScoringPolicy,
  SubmissionEntry,
  SubmissionsByChallenge,
} from '../../src/api/scoreboard';

/**
 * Format a Date the way the Flask API does, via
 * ref.core.util.datetime_to_string: "DD/MM/YYYY HH:MM:SS" in local time.
 * Tests run with TZ=UTC (see vitest.config.ts), so local is UTC.
 */
export function apiDate(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return (
    `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()} ` +
    `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
  );
}

/** An api-formatted timestamp `offsetMs` away from now. */
export function apiDateOffset(offsetMs: number): string {
  return apiDate(new Date(Date.now() + offsetMs));
}

export const HOUR = 3600_000;
export const DAY = 24 * HOUR;

export function challenge(opts: Partial<ChallengeCfg> = {}): ChallengeCfg {
  return {
    start: apiDateOffset(-DAY),
    end: apiDateOffset(DAY),
    per_task_scoring_policies: {},
    max_points: 10,
    ...opts,
  };
}

/** A challenge whose window is wholly in the past. */
export function pastChallenge(): ChallengeCfg {
  return challenge({ start: apiDateOffset(-2 * DAY), end: apiDateOffset(-DAY) });
}

/** A challenge whose window has not opened yet. */
export function futureChallenge(startInMs = DAY): ChallengeCfg {
  return challenge({
    start: apiDateOffset(startInMs),
    end: apiDateOffset(startInMs + DAY),
  });
}

export function assignments(
  spec: Record<string, Record<string, ChallengeCfg>>,
): Assignments {
  return spec;
}

export function entry(
  score: number | null | undefined,
  tsOffsetMs = -HOUR,
  tasks: Record<string, number | null> = {},
): SubmissionEntry {
  return {
    ts: apiDateOffset(tsOffsetMs),
    score: score as number,
    tasks,
  };
}

/** Build submissions as challenge -> team -> entries. */
export function submissions(
  spec: Record<string, Record<string, SubmissionEntry[]>>,
): SubmissionsByChallenge {
  return spec;
}

export function policy(p: ScoringPolicy): ScoringPolicy {
  return p;
}
