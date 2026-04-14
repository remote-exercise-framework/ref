// Shared Chart.js registration + team-color palette.
//
// Importing this module once (via PointsOverTimeChart / ChallengePlot)
// wires every component we actually use. Tree-shaking keeps the rest of
// Chart.js out of the bundle.

import {
  Chart,
  LineController,
  ScatterController,
  LineElement,
  PointElement,
  LinearScale,
  TimeScale,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import 'chartjs-adapter-date-fns';
import annotationPlugin from 'chartjs-plugin-annotation';
import zoomPlugin from 'chartjs-plugin-zoom';

Chart.register(
  LineController,
  ScatterController,
  LineElement,
  PointElement,
  LinearScale,
  TimeScale,
  Tooltip,
  Legend,
  Filler,
  annotationPlugin,
  zoomPlugin,
);

const PALETTE = [
  '#588b8b', '#c8553d', '#93b7be', '#8ab17d', '#e76f51',
  '#a7b7bd', '#306b76', '#f4a261', '#2a9d8f', '#e9c46a',
];

const teamColors = new Map<string, string>();

export function getTeamColor(team: string): string {
  const cached = teamColors.get(team);
  if (cached) return cached;
  let color: string;
  if (teamColors.size < PALETTE.length) {
    color = PALETTE[teamColors.size];
  } else {
    const hue = ((teamColors.size * 360) / 1.712) % 360;
    color = `hsl(${hue}, 70%, 50%)`;
  }
  teamColors.set(team, color);
  return color;
}

const MARKERS = [
  'circle', 'triangle', 'rect', 'rectRot', 'star',
  'cross', 'crossRot', 'rectRounded', 'dash',
] as const;
export type TeamMarker = (typeof MARKERS)[number];

const teamMarkers = new Map<string, TeamMarker>();

export function getTeamMarker(team: string): TeamMarker {
  const cached = teamMarkers.get(team);
  if (cached) return cached;
  const marker = MARKERS[teamMarkers.size % MARKERS.length];
  teamMarkers.set(team, marker);
  return marker;
}

// The zoom plugin's `limits.x.min` is unreliable for time scales, so we
// additionally clamp in `onPan`/`onZoom` callbacks. Pass a getter so new data
// fetched while the user is interacting can shift the lower bound.
export function makeZoomPanOptions(getXMin: () => number) {
  const clamp = ({ chart }: { chart: Chart }) => {
    const xScale = chart.scales.x;
    if (!xScale) return;
    const xMin = getXMin();
    if (!Number.isFinite(xMin)) return;
    if (xScale.min < xMin) {
      const span = Math.max(xScale.max - xScale.min, 1);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (chart as any).zoomScale('x', { min: xMin, max: xMin + span }, 'none');
    }
  };
  return {
    pan: { enabled: true, mode: 'xy' as const, onPan: clamp },
    zoom: {
      wheel: { enabled: true },
      pinch: { enabled: true },
      drag: { enabled: true, modifierKey: 'shift' as const },
      mode: 'xy' as const,
      onZoom: clamp,
    },
    limits: {
      x: { min: getXMin(), minRange: 60_000 },
    },
  };
}

export { Chart };
