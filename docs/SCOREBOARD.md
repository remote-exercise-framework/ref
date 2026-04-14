# Scoreboard

A public leaderboard at `/v2/scoreboard` that ranks students/teams based
on submission scores. Exercises are grouped into **assignments**
(time-boxed rounds, one per `ExerciseConfig.category`). Each exercise
has a **scoring policy** that transforms raw submission scores into
scoreboard points. The Vue SPA fetches metadata + submissions via two
JSON endpoints and renders rankings, badges, charts, and per-challenge
plots client-side.

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
    scoring_policy: Mapped[Optional[dict]]              # JSON, see below
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

The `scoring_policy` column on `ExerciseConfig` is a JSON object the
admin edits from the exercise config page. `ref/core/scoring.py` exposes
`apply_scoring(raw, policy)` which every API call routes raw scores
through.

Supported modes:

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
on the transformed score; the SPA renders it as a horizontal reference
line on per-challenge plots (typically the score of a naive/trivial
solution).

`validate_scoring_policy(policy)` in the same module returns a list of
human-readable error strings — the exercise-config edit view uses this
to surface admin mistakes before persisting.

## Ranking Strategies

Ranking strategies are registered in `RANKING_STRATEGIES` in
`ref/core/scoring.py`. The active strategy is chosen by the
`SCOREBOARD_RANKING_MODE` system setting and surfaced to the SPA via the
config endpoint. Each strategy has a matching TypeScript module under
`spa-frontend/src/ranking/` that computes the ranking client-side.

| Id | Label | Source |
|----|-------|--------|
| `f1_time_weighted` | Formula 1 (time-weighted) | `spa-frontend/src/ranking/f1_time_weighted.ts` |
| `best_sum` | Sum of best per challenge | `spa-frontend/src/ranking/best_sum.ts` |

Adding a strategy is one dict entry on the Python side plus one `.ts`
file on the frontend.

## API Endpoints

Both endpoints live in `webapp/ref/frontend_api/scoreboard.py`, are
rate-limited, and return `404` when `SCOREBOARD_ENABLED` is off (so the
feature never leaks its existence). No authentication required.

### `GET /api/scoreboard/config`

Assignment/challenge metadata plus the active ranking strategy.

```json
{
  "course_name": "OS-Security",
  "ranking_mode": "f1_time_weighted",
  "assignments": {
    "Assignment 1": {
      "exercise_short_name": {
        "start": "DD/MM/YYYY HH:MM:SS",
        "end":   "DD/MM/YYYY HH:MM:SS",
        "scoring": { "mode": "threshold", "threshold": 0.5, "points": 100, "baseline": 0.013 },
        "max_points": 100
      }
    }
  }
}
```

Only exercises whose default version has finished building and whose
`ExerciseConfig` has both deadline endpoints + a non-null `category` are
included. Empty assignment buckets are pruned.

### `GET /api/scoreboard/submissions`

Submission scores grouped by exercise and team, pre-transformed by
`apply_scoring()`:

```json
{
  "exercise_short_name": {
    "Team A": [["DD/MM/YYYY HH:MM:SS", 87.5], ...]
  }
}
```

Submissions with zero or multiple test results are skipped and logged;
the endpoint expects exactly one top-level test result per submission.
The team label comes from `team_identity(user)`, which returns the
user's group name when groups are enabled, otherwise their full name.

## Frontend

The Vue page at `spa-frontend/src/pages/Scoreboard.vue` polls both API
endpoints and hands the data to the components under
`spa-frontend/src/components/scoreboard/`:

- `RankingTable.vue` — sorted points table with earned badge icons.
- `HighscoreCard.vue` — per-assignment top-score card.
- `PointsOverTimeChart.vue` — cumulative points line chart with
  assignment-boundary annotations.
- `ChallengePlot.vue` — per-challenge scatter of best-ever improvements
  (regressions are filtered out).
- `Countdown.vue` — timer for the currently-running assignment's deadline.

All charts use Chart.js with `chartjs-plugin-zoom` for pan/zoom
(drag-pan, wheel/pinch zoom, shift-drag box zoom) and cap the x-axis at
the earliest data point so users can't drag into empty pre-data space.
Chart data updates on each poll preserve the user's zoom state.

Badges are a visual consequence of crossing a scoring threshold — no
dedicated backend. Badge assets are static SVG files at
`webapp/ref/static/badges/<short_name>.svg` with a default fallback.

## System Settings

| Setting | Type | Purpose |
|---------|------|---------|
| `SCOREBOARD_ENABLED` | bool | Master toggle for the page + JSON endpoints |
| `SCOREBOARD_RANKING_MODE` | str | Selected ranking strategy id |
| `LANDING_PAGE` | str | `"registration"` or `"scoreboard"` — where `/` redirects |

All three are exposed in the admin system-settings form
(`webapp/ref/view/system_settings.py`).
