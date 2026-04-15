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
import type { ScoresOverTime } from '../../ranking/types';

const props = defineProps<{
  scoresOverTime: ScoresOverTime;
  assignmentBoundaries: Date[];
}>();

const root = ref<HTMLDivElement | null>(null);
let chart: ManagedChart | null = null;

function buildSeries() {
  const entries = Object.entries(props.scoresOverTime);
  const mark = getMarkLineColors();
  return entries.map(([team, scores], index) => ({
    id: `team-${team}`,
    name: team,
    type: 'line' as const,
    smooth: false,
    showSymbol: true,
    symbol: getTeamSymbol(team),
    symbolSize: 10,
    data: scores.map(({ time, score }) => ({
      value: [time, score] as [number, number],
    })),
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
    markLine: index === 0 && props.assignmentBoundaries.length > 0
      ? {
          symbol: ['none', 'none'] as ['none', 'none'],
          animation: false,
          label: {
            show: true,
            position: 'middle' as const,
            rotate: 90,
            align: 'center' as const,
            verticalAlign: 'middle' as const,
            color: mark.label,
            formatter: ({ dataIndex }: { dataIndex: number }) =>
              `Assignment ${dataIndex + 1}`,
          },
          lineStyle: {
            color: mark.line,
            type: 'dashed' as const,
            width: 1,
          },
          data: props.assignmentBoundaries.map((time) => ({
            xAxis: time.getTime(),
          })),
        }
      : undefined,
  }));
}

function dataRange(series: Array<{ data: Array<{ value: [number, number] }> }>): {
  min: number;
  max: number;
} {
  let min = Infinity;
  let max = -Infinity;
  for (const item of series) {
    for (const point of item.data) {
      const t = point.value[0];
      if (t < min) min = t;
      if (t > max) max = t;
    }
  }
  return {
    min: Number.isFinite(min) ? min : 0,
    max: Number.isFinite(max) ? max : 0,
  };
}

function buildOption(): EChartsOption {
  const series = buildSeries();
  const { min: dataMin, max: dataMax } = dataRange(series);
  const boundaries = props.assignmentBoundaries.map((d) => d.getTime());
  const allMins = [dataMin, ...boundaries].filter((n) => Number.isFinite(n));
  const allMaxs = [dataMax, ...boundaries].filter((n) => Number.isFinite(n));
  const xMin = allMins.length ? Math.min(...allMins) : 0;
  const xMax = allMaxs.length ? Math.max(...allMaxs) : 0;
  const pad = xMax > xMin ? (xMax - xMin) * 0.02 : 0;
  const common = buildCommonOptions(xMin - pad, xMax + pad);
  return {
    ...common,
    tooltip: {
      ...(common.tooltip ?? {}),
      trigger: 'axis',
      formatter: (raw: unknown) => {
        const params = Array.isArray(raw) ? raw : [raw];
        const items = params as Array<{
          axisValue?: number;
          data?: { value?: [number, number] };
          marker?: string;
          seriesName?: string;
        }>;
        if (!items.length) return '';
        const lines = [formatTooltipDate(Number(items[0].axisValue ?? 0))];
        for (const item of items) {
          const score = Number(item.data?.value?.[1] ?? 0).toFixed(2);
          lines.push(`${item.marker ?? ''}${item.seriesName ?? ''}: ${score}`);
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
watch(() => [props.scoresOverTime, props.assignmentBoundaries], render, {
  deep: true,
});
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
