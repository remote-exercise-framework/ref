<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import type { EChartsOption } from 'echarts';
import {
  buildCommonOptions,
  formatTooltipDate,
  getMarkLineColors,
  getTeamColor,
  getTeamSymbol,
  mountChart,
  onThemeChange,
  unmountChart,
  type ManagedChart,
} from './chartSetup';
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

type PlotPoint = {
  value: [number, number];
  tasks: Record<string, number | null>;
};

const root = ref<HTMLDivElement | null>(null);
let chart: ManagedChart | null = null;

function findBaseline(): number | null {
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

function buildSeries() {
  const teams = (props.submissions && props.submissions[props.challengeName]) || {};
  const baseline = findBaseline();
  const mark = getMarkLineColors();
  return Object.entries(teams).map(([team, points], index) => {
    const parsed = points
      .map((entry) => {
        const d = parseApiDate(entry.ts);
        return d
          ? {
              value: [d.getTime(), Number(entry.score)] as [number, number],
              tasks: entry.tasks ?? {},
            }
          : null;
      })
      .filter((point): point is PlotPoint => point !== null)
      .sort((a, b) => a.value[0] - b.value[0]);

    const improvements: PlotPoint[] = [];
    let best = -Infinity;
    for (const point of parsed) {
      if (point.value[1] > best) {
        improvements.push(point);
        best = point.value[1];
      }
    }

    return {
      id: `team-${team}`,
      name: team,
      type: 'line' as const,
      smooth: false,
      showSymbol: true,
      symbol: getTeamSymbol(team),
      symbolSize: 10,
      data: improvements,
      lineStyle: {
        width: 2,
        color: getTeamColor(team),
      },
      itemStyle: {
        color: getTeamColor(team),
      },
      emphasis: {
        focus: 'series' as const,
      },
      markLine: index === 0 && baseline !== null
        ? {
            symbol: ['none', 'none'] as ['none', 'none'],
            animation: false,
            label: {
              show: true,
              position: 'insideMiddleTop' as const,
              distance: 4,
              formatter: 'baseline',
              color: mark.label,
            },
            lineStyle: {
              color: mark.line,
              type: 'dashed' as const,
              width: 1,
            },
            data: [{ yAxis: baseline }],
          }
        : undefined,
    };
  });
}

function earliestX(series: Array<{ data: PlotPoint[] }>): number {
  let min = Infinity;
  for (const item of series) {
    for (const point of item.data) {
      if (point.value[0] < min) min = point.value[0];
    }
  }
  return Number.isFinite(min) ? min : 0;
}

function buildOption(): EChartsOption {
  const series = buildSeries();
  const xMin = earliestX(series);
  const common = buildCommonOptions(xMin);
  return {
    ...common,
    tooltip: {
      ...(common.tooltip ?? {}),
      trigger: 'item',
      formatter: (raw: unknown) => {
        const item = raw as {
          data?: PlotPoint;
          marker?: string;
          seriesName?: string;
        };
        const point = item.data;
        if (!point) return '';
        const lines = [
          formatTooltipDate(point.value[0]),
          `${item.marker ?? ''}${item.seriesName ?? ''}: ${point.value[1].toFixed(2)}`,
        ];
        const entries = Object.entries(point.tasks || {});
        if (entries.length > 1) {
          lines.push('', 'Tasks:');
          for (const [name, score] of entries) {
            lines.push(
              `${name}: ${score === null ? 'untested' : Number(score).toFixed(2)}`,
            );
          }
        }
        return lines.join('<br/>');
      },
    },
    series,
  };
}

function render() {
  if (!root.value) return;
  if (!chart) chart = mountChart(root.value);
  chart.chart.setOption(buildOption());
}

let offTheme: (() => void) | null = null;

onMounted(() => {
  render();
  offTheme = onThemeChange(render);
});
watch(() => props.challengeName, render);
watch(
  () => [props.assignments, props.submissions],
  render,
  { deep: true },
);
onBeforeUnmount(() => {
  offTheme?.();
  offTheme = null;
  unmountChart(chart);
  chart = null;
});
</script>

<template>
  <div class="term-panel term-chart-wrap">
    <div ref="root" class="term-chart" />
  </div>
</template>
