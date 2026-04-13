// Shared helpers + ranking-strategy dispatcher for the scoreboard.
//
// Strategy modules live under ./ranking/<id>.js and each export the same
// interface. The dispatcher dynamic-imports the active strategy on first
// call based on the `ranking_mode` field from /api/scoreboard/config and
// caches it.

const strategyCache = new Map();

export async function loadStrategy(mode) {
    if (strategyCache.has(mode)) return strategyCache.get(mode);
    const mod = await import(`./ranking/${mode}.js`);
    strategyCache.set(mode, mod);
    return mod;
}

// ---------------------------------------------------------------------------
// Date parsing (API emits "DD/MM/YYYY HH:MM:SS" via datetime_to_string).
// ---------------------------------------------------------------------------

export function parseApiDate(ts) {
    if (!ts) return null;
    if (ts instanceof Date) return new Date(ts.getTime());
    if (typeof ts !== 'string') return null;
    const [datePart, timePart] = ts.trim().split(' ');
    if (!datePart || !timePart) return null;
    const [dd, mm, yyyy] = datePart.split('/').map(Number);
    const [HH, MM, SS] = timePart.split(':').map(Number);
    const d = new Date(yyyy, mm - 1, dd, HH, MM, SS, 0);
    return Number.isNaN(d.getTime()) ? null : d;
}

export function extractTeamAcronym(teamStr) {
    if (!teamStr || typeof teamStr !== 'string') return teamStr || 'None';
    const match = teamStr.match(/\(([^()]+)\)\s*$/);
    return match ? match[1].trim() : teamStr;
}

export function hoursSince(ts) {
    const when = parseApiDate(ts);
    if (!when) return '–';
    const ms = Date.now() - when.getTime();
    if (ms < 0) return '0h';
    return `${Math.floor(ms / 3600000)}h`;
}

// ---------------------------------------------------------------------------
// Strategy-independent helpers
//
// These operate over the `assignments` data structure returned by
// /api/scoreboard/config: `{ "<assignment name>": { "<challenge>": { start,
// end, scoring, max_points }, ... }, ... }`.
// ---------------------------------------------------------------------------

// Highest transformed score per (challenge, team) so far.
// Returns { challenge: [team, score, tsStr] } keyed by best score.
export function getHighscores(assignments, submissions) {
    const highscores = {};
    for (const challenge of Object.keys(submissions || {})) {
        let best = null;
        const teams = submissions[challenge] || {};
        for (const team of Object.keys(teams)) {
            for (const [tsStr, rawScore] of teams[team] || []) {
                const score = Number(rawScore);
                const ts = parseApiDate(tsStr);
                if (!ts || Number.isNaN(score)) continue;
                if (!best || score > best.score ||
                    (score === best.score && ts < best.ts)) {
                    best = { team, score, ts, tsStr };
                }
            }
        }
        if (best) highscores[challenge] = [best.team, best.score, best.tsStr];
    }
    return highscores;
}

// A team earns the badge for a challenge iff they earned any transformed
// points for it inside the challenge window.
export function getBadges(assignments, submissions) {
    const badges = {};
    for (const name of Object.keys(assignments || {})) {
        for (const challenge of Object.keys(assignments[name] || {})) {
            const cfg = assignments[name][challenge];
            const cStart = parseApiDate(cfg.start);
            const cEnd = parseApiDate(cfg.end);
            if (!cStart || !cEnd) continue;
            const teams = (submissions && submissions[challenge]) || {};
            for (const team of Object.keys(teams)) {
                let earned = false;
                for (const [tsStr, score] of teams[team] || []) {
                    const ts = parseApiDate(tsStr);
                    if (!ts || ts < cStart || ts > cEnd) continue;
                    if (Number(score) > 0) { earned = true; break; }
                }
                if (!badges[team]) badges[team] = [];
                if (earned && !badges[team].includes(challenge)) {
                    badges[team].push(challenge);
                }
            }
        }
    }
    // Ensure every team that shows up in submissions has an entry.
    for (const teams of Object.values(submissions || {})) {
        for (const team of Object.keys(teams || {})) {
            if (!badges[team]) badges[team] = [];
        }
    }
    return badges;
}

// Assignment whose challenges are currently submittable
// (start <= now <= end). If multiple are active at once, pick the one with
// the latest start so the newest open assignment wins. Returns null if
// none is active and the caller should fall back to a default.
export function getActiveAssignmentName(assignments) {
    const now = new Date();
    let best = null;
    let bestStart = null;
    for (const [name, challenges] of Object.entries(assignments || {})) {
        let anyActive = false;
        let earliestStart = null;
        for (const ch of Object.values(challenges || {})) {
            const s = parseApiDate(ch.start);
            const e = parseApiDate(ch.end);
            if (!s || !e) continue;
            if (s <= now && now <= e) anyActive = true;
            if (!earliestStart || s < earliestStart) earliestStart = s;
        }
        if (anyActive && (!bestStart || earliestStart > bestStart)) {
            best = name;
            bestStart = earliestStart;
        }
    }
    return best;
}

export function computeAssignmentStartTimes(assignments) {
    const times = [];
    for (const challenges of Object.values(assignments || {})) {
        let earliest = null;
        for (const ch of Object.values(challenges || {})) {
            const s = parseApiDate(ch.start);
            if (s && (!earliest || s < earliest)) earliest = s;
        }
        if (earliest) times.push(earliest);
    }
    times.sort((a, b) => a - b);
    return times;
}

// Collect challenge windows across all assignments, merged by short_name.
export function collectChallengeWindows(assignments) {
    const windows = {};
    for (const challenges of Object.values(assignments || {})) {
        for (const [name, cfg] of Object.entries(challenges || {})) {
            const start = parseApiDate(cfg.start);
            const end = parseApiDate(cfg.end);
            if (!start || !end) continue;
            if (!windows[name]) windows[name] = [];
            windows[name].push({ start, end, cfg });
        }
    }
    return windows;
}
