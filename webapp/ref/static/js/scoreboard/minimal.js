// Minimal scoreboard view — just a ranking table. Demonstrates that
// switchable views can share the same API + ranking strategies with
// vastly different HTML layouts.

import { loadStrategy, getBadges } from '../utils.js';

const POLL_INTERVAL_MS = 5000;

async function fetchJson(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${url} → ${res.status}`);
    return res.json();
}

async function update() {
    const [config, submissions] = await Promise.all([
        fetchJson('/api/scoreboard/config'),
        fetchJson('/api/scoreboard/submissions'),
    ]);
    const strategy = await loadStrategy(config.ranking_mode);
    const assignments = config.assignments || {};
    const ranking = strategy.getRanking(assignments, submissions);
    const badges = getBadges(assignments, submissions);

    const tbody = document.getElementById('ranking-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';
    if (ranking.length === 0) {
        const row = document.createElement('tr');
        row.innerHTML = '<td colspan="4" class="text-center text-muted">No submissions yet.</td>';
        tbody.appendChild(row);
        return;
    }
    ranking.forEach(([team, score], index) => {
        const row = document.createElement('tr');
        const teamBadges = (badges[team] || [])
            .map(
                (b) => `
                <img src="/static/badges/${b}.svg"
                     onerror="this.onerror=null;this.src='/static/badges/default.svg';"
                     title="${b}"
                     style="height:1.2em; margin:0 0.1em;">
            `
            )
            .join('');
        row.innerHTML = `
            <th scope="row">${index + 1}</th>
            <td>${team}</td>
            <td>${teamBadges}</td>
            <td class="text-right">${Number(score).toFixed(2)}</td>
        `;
        tbody.appendChild(row);
    });
}

function start() {
    update().catch(console.error);
    setInterval(() => update().catch(console.error), POLL_INTERVAL_MS);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
} else {
    start();
}
