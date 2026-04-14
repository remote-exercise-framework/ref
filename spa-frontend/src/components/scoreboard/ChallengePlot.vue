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
  for (const challenges of Object.values(props.assignments || {})) {
    const cfg = challenges[props.challengeName];
    if (cfg && cfg.scoring && typeof cfg.scoring.baseline === 'number') {
      return cfg.scoring.baseline;
    }
  }
  return null;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function buildDatasets(): any[] {
  const teams = (props.submissions && props.submissions[props.challengeName]) || {};
  return Object.entries(teams).map(([team, points]) => {
    const parsed = points
      .map(([tsStr, score]) => {
        const d = parseApiDate(tsStr);
        return d ? { x: d.getTime(), y: Number(score) } : null;
      })
      .filter((p): p is { x: number; y: number } => p !== null)
      .sort((a, b) => a.x - b.x);
    const improvements: { x: number; y: number }[] = [];
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
