<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { Chart, getTeamColor, getTeamMarker, makeZoomPanOptions } from './chartSetup';
import { parseApiDate } from '../../ranking/util';
import type {
  Assignments,
  SubmissionsByChallenge,
} from '../../api/scoreboard';

const props = defineProps<{
  challengeName: string;
  assignments: Assignments;
  submissions: SubmissionsByChallenge;
}>();

const canvas = ref<HTMLCanvasElement | null>(null);
let chart: Chart | null = null;
let xMinCache = 0;

function findBaseline(): number | null {
  // The plot's baseline line is drawn at the sum of per-task baselines
  // (each task's policy may optionally carry one). Returns null if no
  // task has a baseline configured.
  for (const challenges of Object.values(props.assignments || {})) {
    const cfg = challenges[props.challengeName];
    if (!cfg || !cfg.per_task_scoring_policies) continue;
    let total = 0;
    let any = false;
    for (const policy of Object.values(cfg.per_task_scoring_policies)) {
      if (policy && typeof policy.baseline === 'number') {
        total += policy.baseline;
        any = true;
      }
    }
    if (any) return total;
  }
  return null;
}

type PlotPoint = {
  x: number;
  y: number;
  tasks: Record<string, number | null>;
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function buildDatasets(): any[] {
  const teams = (props.submissions && props.submissions[props.challengeName]) || {};
  return Object.entries(teams).map(([team, points]) => {
    const parsed = points
      .map((entry) => {
        const d = parseApiDate(entry.ts);
        return d
          ? {
              x: d.getTime(),
              y: Number(entry.score),
              tasks: entry.tasks ?? {},
            }
          : null;
      })
      .filter((p): p is PlotPoint => p !== null)
      .sort((a, b) => a.x - b.x);
    const improvements: PlotPoint[] = [];
    let best = -Infinity;
    for (const p of parsed) {
      if (p.y > best) {
        improvements.push(p);
        best = p.y;
      }
    }
    return {
      label: team,
      data: improvements,
      borderColor: getTeamColor(team),
      backgroundColor: getTeamColor(team),
      pointStyle: getTeamMarker(team),
      showLine: true,
      fill: false,
      pointRadius: 6,
      pointHoverRadius: 8,
    };
  });
}

function earliestX(datasets: { data: { x: number }[] }[]): number {
  let min = Infinity;
  for (const ds of datasets) {
    for (const pt of ds.data) if (pt.x < min) min = pt.x;
  }
  return Number.isFinite(min) ? min : 0;
}

function render() {
  if (!canvas.value) return;
  if (chart) chart.destroy();

  const datasets = buildDatasets();
  xMinCache = earliestX(datasets);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const annotations: Record<string, any> = {};
  const baseline = findBaseline();
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

  chart = new Chart(canvas.value, {
    type: 'scatter',
    data: { datasets },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { type: 'time', time: { tooltipFormat: 'dd/MM HH:mm' } },
        y: { beginAtZero: true },
      },
      plugins: {
        annotation: { annotations },
        legend: { labels: { usePointStyle: true } },
        zoom: makeZoomPanOptions(() => xMinCache),
        tooltip: {
          callbacks: {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            label: (ctx: any) =>
              `${ctx.dataset.label ?? ''}: ${Number(ctx.parsed.y).toFixed(2)}`,
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            afterBody: (items: any[]) => {
              if (!items.length) return [];
              const raw = items[0].raw as PlotPoint | undefined;
              const tasks = raw?.tasks;
              if (!tasks || Object.keys(tasks).length < 2) return [];
              const lines = ['', 'Tasks:'];
              for (const [name, score] of Object.entries(tasks)) {
                const rendered =
                  score === null ? 'untested' : Number(score).toFixed(2);
                lines.push(`  ${name}: ${rendered}`);
              }
              return lines;
            },
          },
        },
      },
    },
  });
}

function updateData() {
  if (!chart) return render();
  const datasets = buildDatasets();
  chart.data.datasets = datasets;
  xMinCache = earliestX(datasets);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const zoomOpts = (chart.options.plugins as any)?.zoom;
  if (zoomOpts?.limits?.x) zoomOpts.limits.x.min = xMinCache;
  chart.update('none');
}

onMounted(render);
// A challenge switch needs a full rebuild (new baseline annotation); data-only
// updates reuse the chart so user zoom/pan state survives polling refreshes.
watch(() => props.challengeName, render);
watch(
  () => [props.assignments, props.submissions],
  updateData,
  { deep: true },
);
onBeforeUnmount(() => {
  if (chart) chart.destroy();
});
</script>

<template>
  <div class="term-panel term-chart-wrap">
    <canvas ref="canvas" />
  </div>
</template>
