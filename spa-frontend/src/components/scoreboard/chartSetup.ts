import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { EChartsOption } from 'echarts';

type EChartsInstance = ReturnType<typeof echarts.init>;

echarts.use([
  LineChart,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
  CanvasRenderer,
]);

const PALETTE_DARK = [
  '#7fd1d1', '#ff7a5c', '#c8e0e4', '#a9d49a', '#ffa07a',
  '#d0d9dc', '#5fb8c4', '#ffc27a', '#4fd1b8', '#ffdc7a',
];

const PALETTE_LIGHT = [
  '#1f5b5b', '#a6351f', '#1e4a66', '#3d6a2a', '#8a3a1a',
  '#465566', '#0e3a44', '#6b4410', '#0d5f52', '#6b4f05',
];

const SYMBOLS = [
  'circle', 'triangle', 'rect', 'diamond', 'pin',
  'arrow', 'roundRect',
] as const;

const teamIndices = new Map<string, number>();
const teamSymbols = new Map<string, (typeof SYMBOLS)[number]>();

function isLightTheme(): boolean {
  return typeof document !== 'undefined' && document.body.classList.contains('theme-light');
}

type ThemeTokens = {
  axisLabel: string;
  axisLine: string;
  splitLine: string;
  legendText: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
  sliderBorder: string;
  sliderBg: string;
  sliderFill: string;
};

function rgbToken(value: string, alpha?: number): string {
  const triple = value.trim();
  if (!triple) return alpha === undefined ? 'rgb(0,0,0)' : `rgba(0,0,0,${alpha})`;
  return alpha === undefined ? `rgb(${triple})` : `rgba(${triple}, ${alpha})`;
}

function readThemeTokens(): ThemeTokens {
  if (typeof document === 'undefined') {
    return {
      axisLabel: '#b9cbcf',
      axisLine: 'rgba(147,183,190,0.35)',
      splitLine: 'rgba(147,183,190,0.1)',
      legendText: '#d8e7ea',
      tooltipBg: 'rgba(6,17,19,0.92)',
      tooltipBorder: 'rgba(147,183,190,0.35)',
      tooltipText: '#f2f6f7',
      sliderBorder: 'rgba(147,183,190,0.25)',
      sliderBg: 'rgba(147,183,190,0.08)',
      sliderFill: 'rgba(88,139,139,0.2)',
    };
  }
  const style = getComputedStyle(document.body);
  const onSurface = style.getPropertyValue('--v-theme-on-surface');
  const border = style.getPropertyValue('--v-theme-border');
  const surface = style.getPropertyValue('--v-theme-surface');
  const secondary = style.getPropertyValue('--v-theme-secondary');
  const light = isLightTheme();
  return {
    axisLabel: rgbToken(onSurface, light ? 0.85 : 0.78),
    axisLine: rgbToken(border, light ? 0.8 : 0.45),
    splitLine: rgbToken(border, light ? 0.35 : 0.18),
    legendText: rgbToken(onSurface, light ? 0.9 : 0.85),
    tooltipBg: rgbToken(surface, light ? 0.97 : 0.92),
    tooltipBorder: rgbToken(border, light ? 0.7 : 0.45),
    tooltipText: rgbToken(onSurface),
    sliderBorder: rgbToken(border, light ? 0.6 : 0.35),
    sliderBg: rgbToken(border, light ? 0.18 : 0.1),
    sliderFill: rgbToken(secondary, light ? 0.25 : 0.22),
  };
}

const themeListeners = new Set<() => void>();
let themeObserver: MutationObserver | null = null;

function ensureThemeObserver() {
  if (themeObserver || typeof document === 'undefined') return;
  themeObserver = new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.attributeName === 'class') {
        themeListeners.forEach((fn) => fn());
        return;
      }
    }
  });
  themeObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] });
}

export function onThemeChange(listener: () => void): () => void {
  ensureThemeObserver();
  themeListeners.add(listener);
  return () => {
    themeListeners.delete(listener);
  };
}

const tooltipDateFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'short',
  timeStyle: 'short',
});

const axisDateFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'short',
});

const axisTimeFormatter = new Intl.DateTimeFormat(undefined, {
  timeStyle: 'short',
});

export function formatAxisDate(value: number): string {
  return axisDateFormatter.format(new Date(value));
}

export function formatAxisTime(value: number): string {
  return axisTimeFormatter.format(new Date(value));
}

export type ManagedChart = {
  chart: EChartsInstance;
  resizeObserver: ResizeObserver;
};

export function mountChart(el: HTMLDivElement): ManagedChart {
  const chart = echarts.init(el, undefined, { renderer: 'canvas' });
  const resizeObserver = new ResizeObserver(() => {
    chart.resize();
  });
  resizeObserver.observe(el);
  return { chart, resizeObserver };
}

export function unmountChart(instance: ManagedChart | null) {
  if (!instance) return;
  instance.resizeObserver.disconnect();
  instance.chart.dispose();
}

export function getTeamColor(team: string): string {
  let idx = teamIndices.get(team);
  if (idx === undefined) {
    idx = teamIndices.size;
    teamIndices.set(team, idx);
  }
  const palette = isLightTheme() ? PALETTE_LIGHT : PALETTE_DARK;
  if (idx < palette.length) return palette[idx];
  const hue = ((idx * 360) / 1.712) % 360;
  const lightness = isLightTheme() ? 32 : 62;
  return `hsl(${hue}, 65%, ${lightness}%)`;
}

export function getTeamSymbol(team: string): (typeof SYMBOLS)[number] {
  const cached = teamSymbols.get(team);
  if (cached) return cached;
  const symbol = SYMBOLS[teamSymbols.size % SYMBOLS.length];
  teamSymbols.set(team, symbol);
  return symbol;
}

export function formatTooltipDate(value: number): string {
  return tooltipDateFormatter.format(new Date(value));
}

export type MarkLineColors = {
  line: string;
  label: string;
};

export function getMarkLineColors(): MarkLineColors {
  const t = readThemeTokens();
  return { line: t.axisLine, label: t.axisLabel };
}

export function buildCommonOptions(xMin: number, xMax?: number): EChartsOption {
  const t = readThemeTokens();
  return {
    animation: false,
    grid: {
      left: 56,
      right: 24,
      top: 56,
      bottom: 72,
      containLabel: true,
    },
    legend: {
      type: 'scroll',
      top: 14,
      textStyle: { color: t.legendText },
      pageTextStyle: { color: t.legendText },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      borderWidth: 1,
      textStyle: { color: t.tooltipText },
      extraCssText: 'backdrop-filter: blur(8px);',
    },
    xAxis: {
      type: 'time',
      min: xMin || undefined,
      max: xMax || undefined,
      axisLabel: {
        color: t.axisLabel,
        hideOverlap: true,
        formatter: (value: number) => formatAxisDate(value),
      },
      axisLine: { lineStyle: { color: t.axisLine } },
      splitLine: { lineStyle: { color: t.splitLine } },
    },
    yAxis: {
      type: 'value',
      min: 0,
      axisLabel: { color: t.axisLabel },
      axisLine: { lineStyle: { color: t.axisLine } },
      splitLine: { lineStyle: { color: t.splitLine } },
    },
    dataZoom: [
      {
        id: 'inside-x',
        type: 'inside',
        xAxisIndex: 0,
        filterMode: 'none',
        moveOnMouseMove: true,
        zoomOnMouseWheel: true,
        moveOnMouseWheel: false,
      },
      {
        id: 'slider-x',
        type: 'slider',
        xAxisIndex: 0,
        height: 24,
        bottom: 18,
        filterMode: 'none',
        borderColor: t.sliderBorder,
        backgroundColor: t.sliderBg,
        fillerColor: t.sliderFill,
        textStyle: { color: t.axisLabel },
      },
    ],
  };
}
