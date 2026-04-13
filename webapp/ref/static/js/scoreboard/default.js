// Default scoreboard view (retro-terminal). Polls /api/scoreboard/config
// and /api/scoreboard/submissions, picks a ranking strategy at runtime by
// importing /static/js/ranking/<id>.js, renders dynamic assignment tabs,
// highscore cards, ranking table, points chart, and per-challenge plots.
//
// Persists the user's currently-selected assignment and per-assignment
// challenge tab across auto-refreshes so a 5 s poll doesn't yank them
// away from what they were looking at.

import {
    loadStrategy,
    getHighscores,
    getBadges,
    getActiveAssignmentName,
    computeAssignmentStartTimes,
    parseApiDate,
    hoursSince,
} from '../utils.js';

import { renderScorePlot, renderChallengePlots } from '../plots.js';

const POLL_INTERVAL_MS = 5000;
const COUNTDOWN_INTERVAL_MS = 500;

// Runtime state ------------------------------------------------------------

const cache = { config: null, submissions: null, strategy: null, lastModeId: null };

// User selections. `null` means "auto-follow the currently submittable
// assignment". Once a user clicks an assignment tab we lock to their
// choice. Challenge sub-tab selection is per assignment.
let selectedAssignment = null;
const selectedChallenges = {};

// Structure signature — lets us rebuild the tabs/panels only when the
// shape of the data actually changes (adds/removes), leaving Chart.js
// canvases and user tab selections untouched the rest of the time.
let lastStructureKey = null;

// Data fetching ------------------------------------------------------------

async function fetchJson(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${url} → ${res.status}`);
    return res.json();
}

async function refreshData() {
    const [config, submissions] = await Promise.all([
        fetchJson('/api/scoreboard/config'),
        fetchJson('/api/scoreboard/submissions'),
    ]);
    const modeId = config.ranking_mode;
    if (modeId !== cache.lastModeId) {
        cache.strategy = await loadStrategy(modeId);
        cache.lastModeId = modeId;
    }
    cache.config = config;
    cache.submissions = submissions;
    return cache;
}

function structureKey(assignments) {
    return Object.entries(assignments || {})
        .map(([name, chs]) => `${name}:${Object.keys(chs || {}).sort().join(',')}`)
        .sort()
        .join('|');
}

// Tab + panel builders -----------------------------------------------------

function buildAssignmentTabs(hostId, assignments) {
    const host = document.getElementById(hostId);
    if (!host) return;
    host.innerHTML = '';
    const activeName = getActiveAssignmentName(assignments);
    for (const [name, challenges] of Object.entries(assignments || {})) {
        const li = document.createElement('li');
        const a = document.createElement('a');
        a.dataset.assignment = name;
        a.textContent = name;
        // Any assignment whose window hasn't started yet is disabled.
        const notStarted = Object.values(challenges || {}).every((ch) => {
            const s = parseApiDate(ch.start);
            return s && s > new Date();
        });
        if (notStarted && activeName !== name) {
            a.classList.add('is-disabled');
        }
        a.addEventListener('click', (e) => {
            e.preventDefault();
            if (a.classList.contains('is-disabled')) return;
            selectedAssignment = name;
            applyActiveAssignment(name);
        });
        li.appendChild(a);
        host.appendChild(li);
    }
}

function buildHighscoreShells(assignments) {
    const host = document.getElementById('highscore-assignments');
    if (!host) return;
    host.innerHTML = '';
    for (const name of Object.keys(assignments || {})) {
        const panel = document.createElement('div');
        panel.className = 'sb-assignment-panel';
        panel.dataset.assignment = name;

        const grid = document.createElement('div');
        grid.className = 'sb-highscore-grid';
        grid.dataset.role = 'highscore-grid';
        panel.appendChild(grid);

        const cd = document.createElement('div');
        cd.className = 'sb-countdown';
        cd.dataset.assignment = name;
        cd.innerHTML = `
            <div class="sb-countdown-label">Remaining: 00h 00m 00s</div>
            <div class="sb-countdown-bar"><div class="sb-countdown-fill"></div></div>
        `;
        panel.appendChild(cd);

        host.appendChild(panel);
    }
}

function fillHighscoreCards(assignments, highscores) {
    const host = document.getElementById('highscore-assignments');
    if (!host) return;
    for (const [name, challenges] of Object.entries(assignments || {})) {
        const panel = host.querySelector(
            `.sb-assignment-panel[data-assignment="${CSS.escape(name)}"]`
        );
        if (!panel) continue;
        const grid = panel.querySelector('[data-role="highscore-grid"]');
        if (!grid) continue;
        grid.innerHTML = '';
        for (const challengeName of Object.keys(challenges || {})) {
            const hs = highscores[challengeName];
            const score = hs ? Number(hs[1]).toFixed(2) : '0.00';
            const ts = hs ? hoursSince(hs[2]) : '–';
            const team = hs ? hs[0] : 'n/a';
            const card = document.createElement('div');
            card.className = 'sb-highscore';
            card.innerHTML = `
                <div class="sb-hs-label">${challengeName}</div>
                <div class="sb-hs-score">${score}</div>
                <div class="sb-hs-caption">${team} · ${ts}</div>
            `;
            grid.appendChild(card);
        }
    }
}

function buildChallengeShells(assignments) {
    const host = document.getElementById('challenges-root');
    if (!host) return;
    host.innerHTML = '';
    for (const [name, challenges] of Object.entries(assignments || {})) {
        const section = document.createElement('div');
        section.className = 'sb-assignment-section';
        section.dataset.assignment = name;

        const tabs = document.createElement('ul');
        tabs.className = 'sb-challenge-tabs';
        section.appendChild(tabs);

        const challengeNames = Object.keys(challenges || {});
        const desired = selectedChallenges[name];
        const active = desired && challengeNames.includes(desired)
            ? desired
            : challengeNames[0];

        challengeNames.forEach((challengeName) => {
            const li = document.createElement('li');
            li.className = 'sb-challenge-tab';
            li.dataset.challenge = challengeName;
            if (challengeName === active) li.classList.add('is-active');
            li.textContent = challengeName;
            li.addEventListener('click', () => {
                selectedChallenges[name] = challengeName;
                activateChallenge(section, challengeName);
            });
            tabs.appendChild(li);

            const panel = document.createElement('div');
            panel.className = 'sb-challenge-panel';
            panel.dataset.challenge = challengeName;
            if (challengeName === active) panel.classList.add('is-active');
            panel.innerHTML = `<canvas data-challenge="${challengeName}"></canvas>`;
            section.appendChild(panel);
        });

        if (active) selectedChallenges[name] = active;
        host.appendChild(section);
    }
}

function activateChallenge(section, challengeName) {
    section.querySelectorAll('.sb-challenge-tab').forEach((t) =>
        t.classList.toggle('is-active', t.dataset.challenge === challengeName)
    );
    section.querySelectorAll('.sb-challenge-panel').forEach((p) =>
        p.classList.toggle('is-active', p.dataset.challenge === challengeName)
    );
}

// Ranking ------------------------------------------------------------------

function renderRanking(ranking, badges) {
    const tbody = document.getElementById('ranking-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';
    if (!ranking || ranking.length === 0) {
        tbody.innerHTML = '<tr class="sb-empty"><td colspan="4">// awaiting submissions</td></tr>';
        return;
    }
    ranking.forEach(([team, score], index) => {
        const row = document.createElement('tr');
        const teamBadges = (badges[team] || [])
            .map(
                (b) => `<img src="/static/badges/${b}.svg"
                             onerror="this.onerror=null;this.src='/static/badges/default.svg';"
                             title="${b}" alt="${b}">`
            )
            .join('');
        row.innerHTML = `
            <td class="sb-col-rank"><span class="sb-rank">${index + 1}</span></td>
            <td class="sb-team">${team}</td>
            <td><span class="sb-badges">${teamBadges}</span></td>
            <td class="sb-col-points"><span class="sb-points">${Number(score).toFixed(2)}</span></td>
        `;
        tbody.appendChild(row);
    });
}

// Active-assignment management --------------------------------------------

function applyActiveAssignment(name) {
    document
        .querySelectorAll('#highscore-assignments .sb-assignment-panel')
        .forEach((p) => p.classList.toggle('is-active', p.dataset.assignment === name));
    document
        .querySelectorAll('#challenges-root .sb-assignment-section')
        .forEach((s) => s.classList.toggle('is-active', s.dataset.assignment === name));
    document
        .querySelectorAll('#highscore-assignment-tabs a')
        .forEach((a) => a.classList.toggle('is-current', a.dataset.assignment === name));
    document
        .querySelectorAll('#challenges-assignment-tabs a')
        .forEach((a) => a.classList.toggle('is-current', a.dataset.assignment === name));
}

function resolveActiveAssignment(assignments) {
    const names = Object.keys(assignments || {});
    if (selectedAssignment && names.includes(selectedAssignment)) return selectedAssignment;
    // Default to whichever assignment is currently submittable; fall back
    // to the first assignment in the list if none is active right now.
    return getActiveAssignmentName(assignments) || names[0] || null;
}

// Main update loop --------------------------------------------------------

async function updateAll(init = false) {
    const { config, submissions, strategy } = await refreshData();
    const assignments = config.assignments || {};

    const modeLabel = document.getElementById('sb-ranking-mode');
    if (modeLabel) modeLabel.textContent = config.ranking_mode.replace(/_/g, ' ');

    const key = structureKey(assignments);
    const structureChanged = key !== lastStructureKey;

    if (init || structureChanged) {
        buildAssignmentTabs('highscore-assignment-tabs', assignments);
        buildAssignmentTabs('challenges-assignment-tabs', assignments);
        buildHighscoreShells(assignments);
        buildChallengeShells(assignments);
        lastStructureKey = key;
    }

    fillHighscoreCards(assignments, getHighscores(assignments, submissions));

    const activeAssignment = resolveActiveAssignment(assignments);
    if (activeAssignment) applyActiveAssignment(activeAssignment);

    const ranking = strategy.getRanking(assignments, submissions);
    renderRanking(ranking, getBadges(assignments, submissions));

    const scoresOverTime = strategy.computeChartScoresOverTime(assignments, submissions);
    renderScorePlot('scoreChart', scoresOverTime, computeAssignmentStartTimes(assignments).slice(1));

    renderChallengePlots(document.getElementById('challenges-root'), assignments, submissions);
}

async function updateCountdown() {
    if (!cache.config) return;
    const host = document.getElementById('highscore-assignments');
    if (!host) return;
    for (const [name, challenges] of Object.entries(cache.config.assignments || {})) {
        const first = Object.values(challenges || {})[0];
        if (!first) continue;
        const start = parseApiDate(first.start);
        const end = parseApiDate(first.end);
        if (!start || !end) continue;
        const cd = host.querySelector(
            `.sb-countdown[data-assignment="${CSS.escape(name)}"]`
        );
        if (!cd) continue;
        const label = cd.querySelector('.sb-countdown-label');
        const fill = cd.querySelector('.sb-countdown-fill');
        if (!label || !fill) continue;
        const now = new Date();
        const diff = end - now;
        if (diff <= 0) {
            label.textContent = 'Remaining: 00h 00m 00s';
            fill.style.width = '100%';
            continue;
        }
        const totalSeconds = Math.floor(diff / 1000);
        const d = Math.floor(totalSeconds / 86400);
        const h = Math.floor((totalSeconds % 86400) / 3600);
        const m = Math.floor((totalSeconds % 3600) / 60);
        const s = totalSeconds % 60;
        const hms =
            `${String(h).padStart(2, '0')}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
        label.textContent = d > 0
            ? `Remaining: ${d}d ${hms}`
            : `Remaining: ${hms}`;
        const total = (end - start) / 1000;
        const elapsed = (now - start) / 1000;
        fill.style.width = `${Math.max(0, Math.min(100, (elapsed / total) * 100))}%`;
    }
}

function start() {
    updateAll(true).catch(console.error);
    updateCountdown().catch(console.error);
    setInterval(() => updateAll(false).catch(console.error), POLL_INTERVAL_MS);
    setInterval(() => updateCountdown().catch(console.error), COUNTDOWN_INTERVAL_MS);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
} else {
    start();
}
