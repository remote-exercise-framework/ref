// Chart.js rendering helpers for the default scoreboard view.
//
// These functions are strategy-agnostic: they consume the shapes that
// every ranking strategy's `computeChartScoresOverTime` produces, plus
// per-challenge best-scores (derived locally). The only `scoring`-field
// they look at is `challenge.scoring.baseline` — the optional reference
// line drawn on challenge plots.

import { parseApiDate } from './utils.js';

const PALETTE = [
    '#588b8b', '#c8553d', '#93b7be', '#8ab17d', '#e76f51',
    '#a7b7bd', '#306b76', '#f4a261', '#2a9d8f', '#e9c46a',
];
const teamColors = new Map();

function getTeamColor(team) {
    if (teamColors.has(team)) return teamColors.get(team);
    let color;
    if (teamColors.size < PALETTE.length) {
        color = PALETTE[teamColors.size];
    } else {
        const hue = (teamColors.size * 360 / 1.712) % 360;
        color = `hsl(${hue}, 70%, 50%)`;
    }
    teamColors.set(team, color);
    return color;
}

export function renderScorePlot(canvasId, scoresOverTime, assignmentAnnotations) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === 'undefined') return;
    const ctx = canvas.getContext('2d');
    const existing = Chart.getChart(ctx);
    if (existing) existing.destroy();

    const datasets = Object.entries(scoresOverTime).map(([team, scores]) => ({
        label: team,
        data: scores.map(({ time, score }) => ({ x: new Date(time), y: score })),
        borderColor: getTeamColor(team),
        borderWidth: 2,
        fill: false,
        pointRadius: 3,
        pointHoverRadius: 5,
        pointBackgroundColor: getTeamColor(team),
    }));

    const annotations = Object.fromEntries(
        (assignmentAnnotations || []).map((t, i) => [
            `assignment-${i}`,
            {
                type: 'line',
                borderColor: 'lightgray',
                borderDash: [6, 6],
                borderWidth: 1,
                scaleID: 'x',
                value: t,
                label: { content: `Assignment ${i + 1}`, display: true },
            },
        ])
    );

    new Chart(ctx, {
        type: 'line',
        data: { datasets },
        options: {
            animation: false,
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { type: 'time', time: { tooltipFormat: 'DD/MM HH:mm' } },
                y: { beginAtZero: true },
            },
            plugins: { annotation: { annotations } },
        },
    });
}

// Render one Chart.js plot per challenge showing each team's raw
// submissions in order. The `challenge.scoring.baseline` (if set) is drawn
// as a dashed horizontal reference line.
export function renderChallengePlots(root, assignments, submissions) {
    if (!root || typeof Chart === 'undefined') return;
    const orderedChallenges = [];
    for (const challenges of Object.values(assignments || {})) {
        for (const name of Object.keys(challenges || {})) {
            if (!orderedChallenges.includes(name)) orderedChallenges.push(name);
        }
    }
    for (const name of orderedChallenges) {
        const canvas = root.querySelector(`canvas[data-challenge="${name}"]`);
        if (!canvas) continue;
        const ctx = canvas.getContext('2d');
        const existing = Chart.getChart(ctx);
        if (existing) existing.destroy();

        const teams = (submissions && submissions[name]) || {};
        const datasets = Object.entries(teams).map(([team, points]) => ({
            label: team,
            data: points.map(([tsStr, score]) => {
                const d = parseApiDate(tsStr);
                return d ? { x: d, y: Number(score) } : null;
            }).filter(Boolean),
            borderColor: getTeamColor(team),
            showLine: true,
            fill: false,
            pointRadius: 3,
        }));

        // Baseline annotation — look up the first config that carries one.
        let baseline = null;
        for (const challenges of Object.values(assignments || {})) {
            if (challenges[name] && challenges[name].scoring) {
                const b = challenges[name].scoring.baseline;
                if (typeof b === 'number') { baseline = b; break; }
            }
        }
        const annotations = {};
        if (baseline !== null) {
            annotations.baseline = {
                type: 'line',
                borderColor: '#aaaaaa',
                borderDash: [4, 4],
                borderWidth: 1,
                scaleID: 'y',
                value: baseline,
                label: { content: 'baseline', display: true },
            };
        }

        new Chart(ctx, {
            type: 'scatter',
            data: { datasets },
            options: {
                animation: false,
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { tooltipFormat: 'DD/MM HH:mm' } },
                    y: { beginAtZero: true },
                },
                plugins: { annotation: { annotations } },
            },
        });
    }
}
