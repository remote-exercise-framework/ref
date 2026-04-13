# Vendored scoreboard assets

The default scoreboard view uses Chart.js (plus moment.js for the time
axis adapter and the annotation plugin for baseline lines). These files
live here instead of being pulled from a CDN at runtime.

| File | Upstream |
| --- | --- |
| `chart.js` | https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js |
| `chartjs-plugin-annotation.js` | https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js |
| `moment.min.js` | https://cdn.jsdelivr.net/npm/moment@2.29.4/min/moment.min.js |
| `chartjs-adapter-moment.min.js` | https://cdn.jsdelivr.net/npm/chartjs-adapter-moment@1.0.1/dist/chartjs-adapter-moment.min.js |

Fonts (Major Mono Display, IBM Plex Mono) are loaded from Google Fonts
at render time. The `minimal` view has no runtime dependencies.
