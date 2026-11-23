import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * chartSetup.ts keeps `teamIndices`, `teamSymbols`, `themeListeners` and a
 * module-global MutationObserver that nothing ever clears, plus three
 * Intl.DateTimeFormat instances built at import time. So every test here
 * imports a fresh copy through `load()`; a static import would carry the
 * previous test's team→colour assignments.
 *
 * One test deliberately skips the reset, to prove the leak is real rather
 * than hypothetical.
 */
type ChartSetup = typeof import('../../../src/components/scoreboard/chartSetup');

async function load(): Promise<ChartSetup> {
  vi.resetModules();
  return import('../../../src/components/scoreboard/chartSetup');
}

/** Without a reset, so the module state carries over from the last load. */
async function loadWithoutReset(): Promise<ChartSetup> {
  return import('../../../src/components/scoreboard/chartSetup');
}

function setTheme(which: 'light' | 'dark') {
  document.body.classList.remove('theme-light', 'theme-dark');
  document.body.classList.add(`theme-${which}`);
}

describe('chartSetup', () => {
  beforeEach(() => {
    document.body.className = '';
  });

  afterEach(() => {
    document.body.className = '';
  });

  describe('rgbToken', () => {
    it('wraps a bare triple in rgb()', async () => {
      const { rgbToken } = await load();

      expect(rgbToken('18, 52, 86')).toBe('rgb(18, 52, 86)');
    });

    it('wraps a triple in rgba() when given an alpha', async () => {
      const { rgbToken } = await load();

      expect(rgbToken('18, 52, 86', 0.5)).toBe('rgba(18, 52, 86, 0.5)');
    });

    it('trims the surrounding whitespace a CSS variable comes with', async () => {
      // getPropertyValue returns a leading space for most declarations.
      const { rgbToken } = await load();

      expect(rgbToken('  18, 52, 86  ')).toBe('rgb(18, 52, 86)');
    });

    it('falls back to black for an empty value', async () => {
      // jsdom resolves every --v-theme-* variable to '', which is exactly
      // this branch — so it is the one the component tests actually hit.
      const { rgbToken } = await load();

      expect(rgbToken('')).toBe('rgb(0,0,0)');
      expect(rgbToken('   ')).toBe('rgb(0,0,0)');
    });

    it('falls back to transparent-capable black when an alpha is given', async () => {
      const { rgbToken } = await load();

      expect(rgbToken('', 0.25)).toBe('rgba(0,0,0,0.25)');
    });

    it('treats an alpha of 0 as given rather than absent', async () => {
      const { rgbToken } = await load();

      expect(rgbToken('1, 2, 3', 0)).toBe('rgba(1, 2, 3, 0)');
    });
  });

  describe('getTeamColor', () => {
    it('is stable for one team across calls', async () => {
      const { getTeamColor } = await load();

      expect(getTeamColor('alice')).toBe(getTeamColor('alice'));
    });

    it('hands distinct teams distinct palette entries', async () => {
      const { getTeamColor } = await load();

      const colors = ['a', 'b', 'c', 'd'].map(getTeamColor);

      expect(new Set(colors).size).toBe(4);
    });

    it('keeps a team on the same palette slot when the theme flips', async () => {
      // The index is cached but the palette is not, so the same team gets
      // the light palette's entry at its own index — a different colour
      // for the same position.
      const { getTeamColor } = await load();
      setTheme('dark');
      const dark = getTeamColor('alice');

      setTheme('light');
      const light = getTeamColor('alice');

      expect(light).not.toBe(dark);
      // Second team still lands one slot along in both themes.
      setTheme('dark');
      const darkSecond = getTeamColor('bob');
      setTheme('light');
      const lightSecond = getTeamColor('bob');
      expect(darkSecond).not.toBe(dark);
      expect(lightSecond).not.toBe(light);
    });

    it('generates an hsl colour once the palette is exhausted', async () => {
      const { getTeamColor } = await load();
      // Ten palette entries, so the eleventh team spills over.
      const teams = Array.from({ length: 11 }, (_, i) => `team${i}`);

      const colors = teams.map(getTeamColor);

      expect(colors.slice(0, 10).every((c) => c.startsWith('#'))).toBe(true);
      expect(colors[10]).toMatch(/^hsl\(/);
    });

    it('darkens the generated colour under the light theme', async () => {
      const { getTeamColor } = await load();
      const teams = Array.from({ length: 11 }, (_, i) => `team${i}`);
      setTheme('dark');
      teams.forEach(getTeamColor);
      const dark = getTeamColor('team10');

      setTheme('light');
      const light = getTeamColor('team10');

      expect(dark).not.toBe(light);
      // Same hue, different lightness.
      const hue = (c: string) => c.slice(c.indexOf('(') + 1, c.indexOf(','));
      expect(hue(light)).toBe(hue(dark));
    });

    it('leaks team assignments across a module instance (known behaviour)', async () => {
      // The Maps are never cleared, so a long-lived SPA keeps growing them
      // and a team's colour depends on how many teams were seen before it.
      // Pinned because it is the reason every other test here resets.
      const fresh = await load();
      fresh.getTeamColor('first');
      const firstColor = fresh.getTeamColor('first');

      const same = await loadWithoutReset();
      const secondColor = same.getTeamColor('second');

      expect(same.getTeamColor('first')).toBe(firstColor);
      expect(secondColor).not.toBe(firstColor);
    });
  });

  describe('getTeamSymbol', () => {
    it('is stable for one team', async () => {
      const { getTeamSymbol } = await load();

      expect(getTeamSymbol('alice')).toBe(getTeamSymbol('alice'));
    });

    it('walks the symbol list for successive teams', async () => {
      const { getTeamSymbol } = await load();

      const symbols = ['a', 'b', 'c'].map(getTeamSymbol);

      expect(new Set(symbols).size).toBe(3);
    });

    it('wraps around once the symbol list is used up', async () => {
      const { getTeamSymbol } = await load();
      const teams = Array.from({ length: 8 }, (_, i) => `t${i}`);

      const symbols = teams.map(getTeamSymbol);

      // Seven symbols, so the eighth repeats the first.
      expect(symbols[7]).toBe(symbols[0]);
    });

    it('is independent of the theme', async () => {
      const { getTeamSymbol } = await load();
      setTheme('dark');
      const dark = getTeamSymbol('alice');

      setTheme('light');

      expect(getTeamSymbol('alice')).toBe(dark);
    });
  });

  describe('date formatting', () => {
    // ICU's default locale differs between this machine and CI, so these
    // compare against an equivalently-configured Intl formatter rather
    // than a literal string.
    const WHEN = Date.UTC(2024, 5, 15, 14, 30, 0);

    it('formats an axis date the way a date-only formatter would', async () => {
      const { formatAxisDate } = await load();
      const expected = new Intl.DateTimeFormat(undefined, { dateStyle: 'short' }).format(
        new Date(WHEN),
      );

      expect(formatAxisDate(WHEN)).toBe(expected);
    });

    it('formats an axis time the way a time-only formatter would', async () => {
      const { formatAxisTime } = await load();
      const expected = new Intl.DateTimeFormat(undefined, { timeStyle: 'short' }).format(
        new Date(WHEN),
      );

      expect(formatAxisTime(WHEN)).toBe(expected);
    });

    it('leaves the year out of the axis time', async () => {
      // Structural rather than literal: the x axis is dense, so the time
      // label must stay short whatever the locale.
      const { formatAxisTime } = await load();

      expect(formatAxisTime(WHEN)).not.toContain('2024');
    });

    it('includes both date and time in the tooltip', async () => {
      const { formatTooltipDate } = await load();
      const expected = new Intl.DateTimeFormat(undefined, {
        dateStyle: 'short',
        timeStyle: 'short',
      }).format(new Date(WHEN));

      expect(formatTooltipDate(WHEN)).toBe(expected);
      expect(formatTooltipDate(WHEN).length).toBeGreaterThan(
        (await load()).formatAxisDate(WHEN).length,
      );
    });
  });

  describe('onThemeChange', () => {
    it('fires when the body class changes', async () => {
      const { onThemeChange } = await load();
      const seen = vi.fn();
      const stop = onThemeChange(seen);

      setTheme('light');
      // MutationObserver callbacks are microtask-queued.
      await Promise.resolve();

      expect(seen).toHaveBeenCalled();
      stop();
    });

    it('stops firing after the returned disposer runs', async () => {
      const { onThemeChange } = await load();
      const seen = vi.fn();
      const stop = onThemeChange(seen);

      stop();
      setTheme('light');
      await Promise.resolve();

      expect(seen).not.toHaveBeenCalled();
    });

    it('notifies every registered listener', async () => {
      const { onThemeChange } = await load();
      const a = vi.fn();
      const b = vi.fn();
      const stopA = onThemeChange(a);
      const stopB = onThemeChange(b);

      setTheme('dark');
      await Promise.resolve();

      expect(a).toHaveBeenCalled();
      expect(b).toHaveBeenCalled();
      stopA();
      stopB();
    });
  });

  describe('getMarkLineColors', () => {
    it('returns a line and a label colour', async () => {
      // jsdom cannot resolve --v-theme-* custom properties, so the values
      // come out of rgbToken's empty-string fallback. Shape only.
      const { getMarkLineColors } = await load();

      const colors = getMarkLineColors();

      expect(Object.keys(colors).sort()).toEqual(['label', 'line']);
      expect(colors.line).toMatch(/^rgba?\(/);
      expect(colors.label).toMatch(/^rgba?\(/);
    });
  });

  describe('buildCommonOptions', () => {
    it('builds a time x axis with animation off', async () => {
      const { buildCommonOptions } = await load();

      const opt = buildCommonOptions(1000, 2000);

      expect(opt.animation).toBe(false);
      expect(opt.xAxis).toMatchObject({ type: 'time', min: 1000, max: 2000 });
      expect(opt.yAxis).toMatchObject({ type: 'value', min: 0 });
    });

    it('drops a falsy bound so ECharts picks it itself', async () => {
      // `xMin || undefined` — so 0, which is a legitimate epoch, becomes
      // auto rather than 1970.
      const { buildCommonOptions } = await load();

      const opt = buildCommonOptions(0);

      expect((opt.xAxis as { min?: number }).min).toBeUndefined();
      expect((opt.xAxis as { max?: number }).max).toBeUndefined();
    });

    it('pairs an inside zoom with a slider, both keyed by id', async () => {
      // applyPreservedState matches the previous zoom window on these ids,
      // so they are part of the contract rather than decoration.
      const { buildCommonOptions } = await load();

      const dz = buildCommonOptions(1000) .dataZoom as { id: string; type: string }[];

      expect(dz.map((z) => z.id)).toEqual(['inside-x', 'slider-x']);
      expect(dz.map((z) => z.type)).toEqual(['inside', 'slider']);
    });

    it('keeps both zooms out of filterMode so the series is never trimmed', async () => {
      const { buildCommonOptions } = await load();

      const dz = buildCommonOptions(1000).dataZoom as { filterMode: string }[];

      expect(dz.every((z) => z.filterMode === 'none')).toBe(true);
    });

    it('formats the x axis labels through formatAxisDate', async () => {
      const mod = await load();
      const axis = mod.buildCommonOptions(1000).xAxis as {
        axisLabel: { formatter: (v: number) => string };
      };
      const when = Date.UTC(2024, 0, 2, 3, 4);

      expect(axis.axisLabel.formatter(when)).toBe(mod.formatAxisDate(when));
    });

    it('uses a scrolling legend so many teams still fit', async () => {
      const { buildCommonOptions } = await load();

      expect(buildCommonOptions(1000).legend).toMatchObject({ type: 'scroll' });
    });

    it('produces a tooltip triggered on the axis with a crosshair', async () => {
      const { buildCommonOptions } = await load();

      expect(buildCommonOptions(1000).tooltip).toMatchObject({
        trigger: 'axis',
        axisPointer: { type: 'cross' },
      });
    });
  });

  describe('applyPreservedState', () => {
    /** Just enough of an ECharts instance for getOption(). */
    function fakeChart(option: unknown) {
      return { getOption: () => option } as never;
    }

    it('carries a previous percentage zoom window onto the new option', async () => {
      const { applyPreservedState } = await load();
      const chart = fakeChart({
        dataZoom: [{ id: 'inside-x', start: 25, end: 75 }],
      });

      const out = applyPreservedState(chart, {
        dataZoom: [{ id: 'inside-x', start: 0, end: 100 }],
      });

      expect(out.dataZoom).toEqual([{ id: 'inside-x', start: 25, end: 75 }]);
    });

    it('carries an absolute zoom window too', async () => {
      const { applyPreservedState } = await load();
      const chart = fakeChart({
        dataZoom: [{ id: 'slider-x', startValue: 1000, endValue: 2000 }],
      });

      const out = applyPreservedState(chart, { dataZoom: [{ id: 'slider-x' }] });

      expect(out.dataZoom).toEqual([
        { id: 'slider-x', startValue: 1000, endValue: 2000 },
      ]);
    });

    it('leaves a zoom entry alone when no previous entry shares its id', async () => {
      const { applyPreservedState } = await load();
      const chart = fakeChart({ dataZoom: [{ id: 'other', start: 25 }] });

      const out = applyPreservedState(chart, { dataZoom: [{ id: 'inside-x', start: 0 }] });

      expect(out.dataZoom).toEqual([{ id: 'inside-x', start: 0 }]);
    });

    it('ignores an empty previous zoom array', async () => {
      // The first poll after mount, before the user has touched anything.
      const { applyPreservedState } = await load();
      const chart = fakeChart({ dataZoom: [] });

      const out = applyPreservedState(chart, { dataZoom: [{ id: 'inside-x', start: 10 }] });

      expect(out.dataZoom).toEqual([{ id: 'inside-x', start: 10 }]);
    });

    it('carries the legend selection across a re-render', async () => {
      // This is what stops a 5-second poll from un-hiding every team the
      // user clicked off.
      const { applyPreservedState } = await load();
      const chart = fakeChart({ legend: [{ selected: { alice: false, bob: true } }] });

      const out = applyPreservedState(chart, { legend: { type: 'scroll' } });

      expect(out.legend).toMatchObject({
        type: 'scroll',
        selected: { alice: false, bob: true },
      });
    });

    it('keeps the legend an array when it was given as one', async () => {
      const { applyPreservedState } = await load();
      const chart = fakeChart({ legend: [{ selected: { alice: false } }] });

      const out = applyPreservedState(chart, { legend: [{ type: 'scroll' }] });

      expect(Array.isArray(out.legend)).toBe(true);
      expect((out.legend as { selected: unknown }[])[0].selected).toEqual({ alice: false });
    });

    it('copies the selection rather than aliasing it', async () => {
      // Otherwise a later ECharts mutation of its own option object would
      // reach back into the one we just built.
      const { applyPreservedState } = await load();
      const selected = { alice: false };
      const chart = fakeChart({ legend: [{ selected }] });

      const out = applyPreservedState(chart, { legend: { type: 'scroll' } });
      selected.alice = true;

      expect((out.legend as { selected: Record<string, boolean> }).selected.alice).toBe(false);
    });

    it('does nothing when there is no previous state at all', async () => {
      const { applyPreservedState } = await load();
      const chart = fakeChart({});
      const option = { dataZoom: [{ id: 'inside-x', start: 0 }], legend: { type: 'scroll' } };

      const out = applyPreservedState(chart, option as never);

      expect(out).toEqual(option);
    });
  });

  describe('mountChart / unmountChart', () => {
    it('disposes the chart and disconnects the observer', async () => {
      const { unmountChart } = await load();
      const dispose = vi.fn();
      const disconnect = vi.fn();

      unmountChart({
        chart: { dispose } as never,
        resizeObserver: { disconnect } as never,
      });

      expect(dispose).toHaveBeenCalledOnce();
      expect(disconnect).toHaveBeenCalledOnce();
    });

    it('tolerates being handed null', async () => {
      // The components call it from onBeforeUnmount with a ref that may
      // never have been filled.
      const { unmountChart } = await load();

      expect(() => unmountChart(null)).not.toThrow();
    });
  });
});
