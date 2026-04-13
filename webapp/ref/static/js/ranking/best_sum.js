// Simple ranking strategy: total = sum of each team's best transformed
// score per challenge. No time-weighting, no per-second accrual. This is
// the second switchable option alongside f1_time_weighted; the two share
// the same interface so scoreboard views can pick either at runtime.

import { parseApiDate } from '../utils.js';

export const id = 'best_sum';
export const label = 'Sum of best per challenge';

function bestPerChallenge(assignments, submissions) {
    // { challenge: { team: bestScore } }
    const best = {};
    for (const challenges of Object.values(assignments || {})) {
        for (const [name, cfg] of Object.entries(challenges || {})) {
            const cStart = parseApiDate(cfg.start);
            const cEnd = parseApiDate(cfg.end);
            if (!cStart || !cEnd) continue;
            const teams = (submissions && submissions[name]) || {};
            if (!best[name]) best[name] = {};
            for (const team of Object.keys(teams)) {
                for (const [tsStr, raw] of teams[team] || []) {
                    const ts = parseApiDate(tsStr);
                    if (!ts || ts < cStart || ts > cEnd) continue;
                    const score = Number(raw);
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

export function getRanking(assignments, submissions) {
    const best = bestPerChallenge(assignments, submissions);
    const totals = {};
    for (const teams of Object.values(best)) {
        for (const [team, score] of Object.entries(teams)) {
            totals[team] = (totals[team] || 0) + score;
        }
    }
    return Object.entries(totals).sort((a, b) => b[1] - a[1]);
}

export function getRates(assignments, submissions) {
    // Not meaningful for this strategy — return per-team empty placeholders
    // so consumers can always read challengeRanks / challengeRates without
    // special-casing.
    const best = bestPerChallenge(assignments, submissions);
    const out = {};
    for (const [challenge, teams] of Object.entries(best)) {
        const sorted = Object.entries(teams)
            .sort((a, b) => (b[1] - a[1]) || (a[0] < b[0] ? -1 : 1))
            .map(([team]) => team);
        for (let i = 0; i < sorted.length; i++) {
            const team = sorted[i];
            if (!out[team]) out[team] = { challengeRanks: {}, challengeRates: {} };
            out[team].challengeRanks[challenge] = i + 1;
            out[team].challengeRates[challenge] = 0;
        }
    }
    return out;
}

// Staircase chart: each team is a step function that jumps at each
// submission by the delta to their best-so-far per challenge.
export function computeChartScoresOverTime(assignments, submissions) {
    const teamSet = new Set();
    for (const teams of Object.values(submissions || {})) {
        for (const team of Object.keys(teams)) teamSet.add(team);
    }
    const out = {};
    for (const team of teamSet) out[team] = [];

    const events = [];
    for (const challenges of Object.values(assignments || {})) {
        for (const [name, cfg] of Object.entries(challenges || {})) {
            const cStart = parseApiDate(cfg.start);
            const cEnd = parseApiDate(cfg.end);
            if (!cStart || !cEnd) continue;
            const teams = (submissions && submissions[name]) || {};
            for (const team of Object.keys(teams)) {
                for (const [tsStr, raw] of teams[team] || []) {
                    const ts = parseApiDate(tsStr);
                    if (!ts || ts < cStart || ts > cEnd) continue;
                    events.push({ ts, team, challenge: name, score: Number(raw) });
                }
            }
        }
    }
    events.sort((a, b) => a.ts - b.ts);

    const bestPer = {}; // team -> challenge -> bestScore
    const totals = {};
    for (const team of teamSet) { bestPer[team] = {}; totals[team] = 0; }

    for (const ev of events) {
        const prev = bestPer[ev.team][ev.challenge] || 0;
        if (ev.score > prev) {
            totals[ev.team] += (ev.score - prev);
            bestPer[ev.team][ev.challenge] = ev.score;
        }
        out[ev.team].push({ time: ev.ts.getTime(), score: totals[ev.team] });
    }
    // Ensure every team has at least one point so the chart renders.
    const nowMs = Date.now();
    for (const team of teamSet) {
        if (out[team].length === 0) out[team].push({ time: nowMs, score: 0 });
    }
    return out;
}
