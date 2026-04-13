// Formula-1 style time-weighted ranking.
//
// Ported from raid/raid's webapp/ref/static/js/utils.js. For every challenge
// the leaderboard is sorted by the best transformed score each team has
// achieved so far; points are then accrued per-second to each ranked team
// proportional to a harmonic weight. The overall ranking is the sum of
// points across all challenges and assignments.

import { parseApiDate } from '../utils.js';

export const id = 'f1_time_weighted';
export const label = 'Formula 1 (time-weighted)';

const RANK_POINTS = Array.from({ length: 10 }, (_, i) => 1 / (i + 1));

function buildTimeline(challengeTeams) {
    const events = [];
    for (const team of Object.keys(challengeTeams || {})) {
        for (const [tsStr, score] of challengeTeams[team] || []) {
            const ts = parseApiDate(tsStr);
            if (!ts) continue;
            events.push({ ts, team, score: Number(score) });
        }
    }
    events.sort((a, b) => a.ts - b.ts);
    return events;
}

function calcChallengeTicks(challengeTeams, start, end) {
    const teamTicks = {};
    for (const team of Object.keys(challengeTeams || {})) teamTicks[team] = 0;
    const events = buildTimeline(challengeTeams);
    if (events.length === 0) return teamTicks;

    const bestSoFar = {};
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
    function accrue(toTs) {
        const seconds = Math.max(0, (toTs - lastTs) / 1000);
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

function calcAllTicks(assignments, submissions, globalEnd = null) {
    const ticks = {};
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

export function getRanking(assignments, submissions) {
    const ticks = calcAllTicks(assignments, submissions);
    const ranking = Object.entries(ticks).map(
        ([team, t]) => [team, t / 3600]
    );
    ranking.sort((a, b) => b[1] - a[1]);
    return ranking;
}

export function getRates(assignments, submissions) {
    const now = new Date();
    const allChallenges = new Set();
    for (const challenges of Object.values(assignments || {})) {
        for (const ch of Object.keys(challenges || {})) allChallenges.add(ch);
    }
    for (const ch of Object.keys(submissions || {})) allChallenges.add(ch);

    const teamSet = new Set();
    for (const teams of Object.values(submissions || {})) {
        for (const team of Object.keys(teams)) teamSet.add(team);
    }

    const result = {};
    for (const team of teamSet) {
        result[team] = { challengeRanks: {}, challengeRates: {} };
    }

    for (const challengeName of allChallenges) {
        const cfgs = [];
        for (const challenges of Object.values(assignments || {})) {
            if (challenges[challengeName]) cfgs.push(challenges[challengeName]);
        }
        const bestScores = {};
        for (const cfg of cfgs) {
            const cStart = parseApiDate(cfg.start);
            const cEnd = parseApiDate(cfg.end);
            if (!cStart || !cEnd) continue;
            if (now < cStart) continue;
            const subs = (submissions && submissions[challengeName]) || {};
            for (const team of Object.keys(subs)) {
                for (const [tsStr, raw] of subs[team] || []) {
                    const ts = parseApiDate(tsStr);
                    if (!ts || ts > now || ts > cEnd) continue;
                    const score = Number(raw);
                    if (!Number.isFinite(score)) continue;
                    if (!(team in bestScores) || score > bestScores[team]) {
                        bestScores[team] = score;
                    }
                }
            }
        }
        const sorted = Object.entries(bestScores)
            .sort((a, b) => (b[1] - a[1]) || (a[0] < b[0] ? -1 : 1))
            .map(([team]) => team);
        for (const team of teamSet) {
            const rank = sorted.indexOf(team) + 1;
            result[team].challengeRanks[challengeName] = rank;
            result[team].challengeRates[challengeName] =
                rank > 0 ? RANK_POINTS[rank - 1] : 0;
        }
    }
    return result;
}

export function computeChartScoresOverTime(assignments, submissions, noIntervals = 40) {
    const teamSet = new Set();
    for (const teams of Object.values(submissions || {})) {
        for (const team of Object.keys(teams)) teamSet.add(team);
    }
    if (teamSet.size === 0) return {};

    let minStart = null;
    let maxEnd = null;
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
        const out = {};
        for (const team of teamSet) out[team] = [{ time: nowMs, score: 0 }];
        return out;
    }
    const now = new Date();
    const chartEnd = now < maxEnd ? now : maxEnd;
    const step = (chartEnd - minStart) / noIntervals;
    if (step <= 0) {
        const out = {};
        for (const team of teamSet) out[team] = [{ time: minStart.getTime(), score: 0 }];
        return out;
    }
    const out = {};
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
