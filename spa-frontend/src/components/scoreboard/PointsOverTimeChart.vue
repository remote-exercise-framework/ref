<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { Chart, getTeamColor, getTeamMarker, makeZoomPanOptions } from './chartSetup';
import type { ScoresOverTime } from '../../ranking/types';

const props = defineProps<{
  scoresOverTime: ScoresOverTime;
  assignmentBoundaries: Date[];
}>();

const canvas = ref<HTMLCanvasElement | null>(null);
let chart: Chart | null = null;
let xMinCache = 0;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function buildDatasets(): any[] {
  return Object.entries(props.scoresOverTime).map(([team, scores]) => ({
    label: team,
    data: scores.map(({ time, score }) => ({ x: time, y: score })),
    borderColor: getTeamColor(team),
    borderWidth: 2,
    fill: false,
    pointStyle: getTeamMarker(team),
    pointRadius: 6,
    pointHoverRadius: 8,
    pointBackgroundColor: getTeamColor(team),
  }));
}

function earliestX(datasets: { data: { x: number }[] }[]): number {
  let min = Infinity;
  for (const ds of datasets) {
    for (const pt of ds.data) if (pt.x < min) min = pt.x;
  }
  return Number.isFinite(min) ? min : 0;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function buildAnnotations(): Record<string, any> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const annotations: Record<string, any> = {};
  (props.assignmentBoundaries || []).forEach((t, i) => {
    annotations[`assignment-${i}`] = {
      type: 'line',
      borderColor: 'gray',
      borderDash: [6, 6],
      borderWidth: 1,
      scaleID: 'x',
      value: t.getTime(),
      label: {
        content: `Assignment ${i + 1}`,
        display: true,
        rotation: -90,
        position: 'center',
        xAdjust: 12,
        yAdjust: -10,
        backgroundColor: 'rgba(0, 0, 0, 0)',
        color: 'gray',
        padding: 0,
      },
    };
  });
  return annotations;
}

function render() {
  if (!canvas.value) return;
  if (chart) chart.destroy();

  const datasets = buildDatasets();
  xMinCache = earliestX(datasets);

  chart = new Chart(canvas.value, {
    type: 'line',
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
        annotation: { annotations: buildAnnotations() },
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
  const plugins = chart.options.plugins as any;
  if (plugins?.annotation) plugins.annotation.annotations = buildAnnotations();
  if (plugins?.zoom?.limits?.x) plugins.zoom.limits.x.min = xMinCache;
  chart.update('none');
}

onMounted(render);
watch(() => [props.scoresOverTime, props.assignmentBoundaries], updateData, {
  deep: true,
});
onBeforeUnmount(() => {
  if (chart) chart.destroy();
});
</script>

<template>
  <div class="term-panel term-chart-wrap">
    <canvas ref="canvas" />
  </div>
</template>
