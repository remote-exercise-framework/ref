# Scoreboard

A public leaderboard at `/spa/scoreboard` that ranks students/teams based
on submission scores. Exercises are grouped into **assignments**
(time-boxed rounds, one per `ExerciseConfig.category`). Each exercise
has **per-task scoring policies** that transform the raw score of each
submission-test task into scoreboard points; the submission's total is
the sum of the transformed per-task scores. The Vue SPA fetches metadata
+ submissions via two JSON endpoints and renders rankings, badges,
charts, and per-challenge plots client-side.

## Data Model

### `ExerciseConfig` (global, web-editable)

Administrative configuration shared across every version of an exercise.
All `Exercise` rows with the same `short_name` point at the same
`ExerciseConfig` row, so editing via the admin UI takes effect
immediately for all versions.

```python
class ExerciseConfig(db.Model):
    id: Mapped[int]                                     # PK
    short_name: Mapped[str]                             # unique
    category: Mapped[Optional[str]]                     # assignment label
    per_task_scoring_policies: Mapped[Optional[dict]]   # JSON: {task_name: policy}
    submission_deadline_start: Mapped[Optional[datetime]]
    submission_deadline_end: Mapped[Optional[datetime]]
    submission_test_enabled: Mapped[bool]
    max_grading_points: Mapped[Optional[int]]
```

`Exercise` carries a `config_id` FK to `ExerciseConfig`; per-version,
build-time fields (`entry_service`, `services`, `build_job_*`,
`template_path`, `persistence_path`, `is_default`, `version`) stay on
`Exercise` itself.

### Raw Scores

Submissions produce a **raw score** (float, stored in
`SubmissionTestResult.score`). Raw scores are persisted unmodified —
scoring policies are applied on read, so policy edits take effect
retroactively without reprocessing stored data.

## Scoring Policies

`ExerciseConfig.per_task_scoring_policies` is a JSON object keyed by
submission-test task name, where each value is a policy dict. The admin
edits it from the exercise config page; task names are auto-discovered
from the exercise's `submission_tests` file via AST parsing
(`ref/core/task_discovery.py::extract_task_names_from_submission_tests`),
so the editor always shows exactly the tasks the test script registers.

`ref/core/scoring.py::score_submission(results, per_task_policies)`
applies each task's policy (or pass-through if the task has no entry)
to that task's raw score and returns `(total, breakdown)` where
`breakdown[task_name]` is the transformed score (or `None` for tasks
whose raw score was `None`). `total` sums the transformed scores;
`None`-scored tasks contribute 0.

Supported policy modes (same shape as `apply_scoring(raw, policy)`):

```
# Linear mapping: raw [min_raw..max_raw] → [0..max_points]
mode: linear
max_points: 100
min_raw: 0.0     # optional, default 0.0
max_raw: 1.0     # optional, default 1.0

# Threshold: all-or-nothing
mode: threshold
threshold: 0.5
points: 100

# Tiered: stepped milestones, highest reached tier wins
mode: tiered
tiers:
  - above: 0.3, points: 25
  - above: 0.6, points: 50
  - above: 0.9, points: 100
```

Any policy may also carry an optional `baseline` field. It has no effect
on the transformed score; the SPA renders the **sum of per-task
baselines** as a horizontal reference line on per-challenge plots
(typically the score of a naive/trivial solution).

`validate_scoring_policy(policy)` in the same module returns a list of
human-readable error strings for a single policy dict — the exercise-
config edit view validates each per-task entry with it before persisting.

## Ranking Strategy

Ranking is computed client-side by
`spa-frontend/src/ranking/best_sum.ts`. Each team's score on a challenge
is their highest in-window submission score, and the ranking score is
the sum of those bests across challenges.

`computeChartScoresOverTime()` emits cumulative points per team over
time for the points-over-time chart. Only submission events that fall
inside an assignment's `[start, end]` window are considered; teams with
no in-window events are omitted from the chart data entirely.

## API Endpoints

Both endpoints live in `webapp/ref/frontend_api/scoreboard.py`, are
rate-limited, and return `404` when `SCOREBOARD_ENABLED` is off (so the
feature never leaks its existence). No authentication required.

### `GET /api/scoreboard/config`

Assignment/challenge metadata.

```json
{
  "course_name": "OS-Security",
  "assignments": {
    "Assignment 1": {
      "exercise_short_name": {
        "start": "DD/MM/YYYY HH:MM:SS",
        "end":   "DD/MM/YYYY HH:MM:SS",
        "per_task_scoring_policies": {
          "coverage": { "mode": "linear", "max_points": 100, "baseline": 0.013 },
          "crashes":  { "mode": "threshold", "threshold": 1, "points": 50 }
        },
        "max_points": 150
      }
    }
  }
}
```

`max_points` is the best-effort sum of each per-task policy's upper
bound (used by the frontend for axis scaling); it is `null` if no task
has a computable maximum. Only exercises whose default version has
finished building and whose `ExerciseConfig` has both deadline endpoints
+ a non-null `category` are included. Empty assignment buckets are
pruned.

### `GET /api/scoreboard/submissions`

Submission scores grouped by exercise and team, pre-transformed via
`score_submission()` with a per-task breakdown:

```json
{
  "exercise_short_name": {
    "Team A": [
      {
        "ts": "DD/MM/YYYY HH:MM:SS",
        "score": 87.5,
        "tasks": { "coverage": 50.0, "crashes": 37.5, "env_check": null }
      }
    ]
  }
}
```

`tasks` values of `null` mean the underlying `SubmissionTestResult.score`
was `None` (bool-returning test, no grading) — consumers render these
as "untested" rather than 0. Such tasks contribute 0 to the outer
`score`. Submissions with no test results at all are skipped. The team
label comes from `team_identity(user)`, which returns the user's group
name when groups are enabled, otherwise their full name.

## Frontend

The Vue page at `spa-frontend/src/pages/Scoreboard.vue` polls both API
endpoints and hands the data to the components under
`spa-frontend/src/components/scoreboard/`:

- `RankingTable.vue` — sorted points table with earned badge icons.
- `HighscoreCard.vue` — per-assignment top-score card.
- `PointsOverTimeChart.vue` — cumulative points line chart with dashed
  vertical markLines at each assignment boundary. The boundary labels
  ("Assignment N") are rotated 90° and sit at the vertical midpoint of
  each line.
- `ChallengePlot.vue` — per-challenge line chart of each team's
  monotonically best score over time (regressions are filtered out).
  When any task has a `baseline`, a horizontal dashed markLine at the
  sum of per-task baselines is drawn with a centered "baseline" label.
- `Countdown.vue` — timer for the currently-running assignment's deadline.

All charts use Apache ECharts with native `dataZoom` on the time axis.
The default interaction model is wheel/pinch zoom plus drag-to-pan on
the x-axis, with a slider scrubber below the chart for coarse
navigation. The x-axis range spans the union of submission timestamps
and assignment boundaries (with 2% padding) so every boundary marker
stays in the viewport even when no data straddles it.

Chart colors (axes, grid, legend, tooltip, data palette, markLine) are
read from the active Vuetify `--v-theme-*` tokens in
`spa-frontend/src/components/scoreboard/chartSetup.ts`. A
`MutationObserver` on `document.body`'s class list watches for theme
toggles and triggers each mounted chart to re-render with the new
tokens, so the light and dark themes each get their own high-contrast
palette without a page reload.

Badges are a visual consequence of crossing a scoring threshold — no
dedicated backend. Badge assets are static SVG files at
`webapp/ref/static/badges/<short_name>.svg` with a default fallback.

## System Settings

| Setting | Type | Purpose |
|---------|------|---------|
| `SCOREBOARD_ENABLED` | bool | Master toggle for the page + JSON endpoints |
| `LANDING_PAGE` | str | `"registration"` or `"scoreboard"` — where `/` redirects |

Both are exposed in the admin system-settings form
(`webapp/ref/view/system_settings.py`).
