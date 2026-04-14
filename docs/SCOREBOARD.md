# Scoreboard Integration

This document describes how to integrate a scoreboard into REF, based on the prototype in the `raid/raid` branch and adapted to the current `dev` codebase.

## Overview

The scoreboard is a public-facing page that shows team/student rankings based on submission scores. Exercises are grouped into **assignments** (time-boxed rounds). Each exercise defines a **scoring policy** that maps raw submission scores to scoreboard points. The frontend fetches data via two JSON APIs and renders rankings, badges, charts, and per-challenge plots client-side.

## What exists in `raid/raid`

The prototype adds:

- **Two API endpoints** (`/api/assignments`, `/api/submissions`) that return exercise metadata and submission scores as JSON.
- **Three new Exercise model fields**: `baseline_score`, `badge_score`, `badge_points` — parsed from the exercise YAML config.
- **A scoreboard page** (`/student/scoreboard`) with a Jinja template and ~2300 lines of client-side JS (`scoreboard.js`, `utils.js`, `plots.js`) using Chart.js.
- **Badges**: per-challenge achievement icons shown in the ranking table when a team's score exceeds `badge_score`. Each challenge can have custom SVG/PNG assets with a default fallback.
- **System settings**: `LANDING_PAGE` (choose which page students see first), `DEMO_MODE_ENABLED` (serve dummy JSON data).
- **A demo/dummy data system** (`dummies/assignments.json`, `dummies/submissions.json`) for development without real submissions.

The prototype is tightly coupled to a fixed 3-assignments x 3-challenges layout and hardcodes assignment/challenge indices in the template. It also bundles all scoring logic (ranking, badges, rates) in the frontend JS.

## What already exists in `dev`

- `SubmissionTestResult.score` (float, nullable) — already in the model. This is the raw per-submission score.
- Exercise `category` field — used as the assignment/group name.
- `Submission.all()`, exercise deadlines, the full submission lifecycle.

## ExerciseConfig: Separating Administrative from Build-Time Config

### Problem

Currently, all exercise configuration lives on the `Exercise` model — one row per version. Administrative fields like deadlines, category, and max grading points are duplicated across versions and synchronized at import time (importing a new version propagates deadlines to all predecessors). This is fragile: editing via a web UI would require updating every version row.

### Solution: `ExerciseConfig` Model

Introduce a new model that holds **administrative configuration** shared across all versions of an exercise:

```python
class ExerciseConfig(db.Model):
    __tablename__ = 'exercise_config'

    id: Mapped[int]                                     # PK (integer)
    short_name: Mapped[str]                             # unique constraint
    category: Mapped[Optional[str]]                     # assignment/group name
    scoring_policy: Mapped[Optional[dict]]              # JSON, see Scoring Architecture
    submission_deadline_start: Mapped[Optional[datetime]]
    submission_deadline_end: Mapped[Optional[datetime]]
    submission_test_enabled: Mapped[bool]
    max_grading_points: Mapped[Optional[int]]
```

The `Exercise` model gets a FK to `ExerciseConfig`:

```python
class Exercise(db.Model):
    # ... existing build-time fields ...
    config_id: Mapped[int] = mapped_column(ForeignKey('exercise_config.id'))
    config: Mapped[ExerciseConfig] = relationship(...)
```

All versions of an exercise with the same `short_name` point to the **same** `ExerciseConfig` row.

### What stays on `Exercise` (per-version, build-time)

- `entry_service` — files, build commands, cmd, flags, resource limits, ASLR, readonly, networking
- `services` — peripheral service configs
- `build_job_status` / `build_job_result`
- `template_path` / `persistence_path` / `template_import_path`
- `is_default`
- `version`

### What moves to `ExerciseConfig` (global, web-editable)

- `category`
- `submission_deadline_start` / `submission_deadline_end`
- `submission_test_enabled`
- `max_grading_points`
- `scoring_policy` (new)

### How it integrates with versioning

- **First import of an exercise:** Creates an `ExerciseConfig` row. Initial values come from the YAML config.
- **Reimport (new version):** Reuses the existing `ExerciseConfig` (looked up by `short_name`). The new `Exercise` row points to the same config. YAML values for administrative fields are **ignored** — the web-edited config takes precedence.
- **Web UI edit:** Updates the single `ExerciseConfig` row — immediately effective for all versions.
- **No more sync logic:** Deadlines no longer need to be propagated across version rows on import.

### Migration path for other config

As more settings move from YAML to web UI, the pattern is:
1. **Build-time?** → stays on `Exercise` (per-version, immutable after build)
2. **Administrative?** → moves to `ExerciseConfig` (global, web-editable)

Future candidates for `ExerciseConfig`: display name, description, visibility/published flag, ordering/priority.

### Web UI: Edit Button

The exercise list page gets an **Edit** button per exercise (per `short_name`, not per version). It opens a form editing the `ExerciseConfig`:

- Category / assignment
- Deadlines (start, end)
- Scoring policy (mode selector + mode-specific fields)
- Max grading points
- Submission test toggle

This is separate from the import flow which handles build-time config.

## Scoring Architecture

### Raw Scores vs. Scoreboard Points

Submissions produce a **raw score** (float, stored in `SubmissionTestResult.score`). This raw score needs to be translated into **scoreboard points** via the exercise's **scoring policy** (stored on `ExerciseConfig`).

### Scoring Policy

The scoring policy is configured via the web UI and stored as a JSON column on `ExerciseConfig`. Supported modes:

```
# Linear mapping: raw [0..1] → [0..max_points]
mode: linear
max_points: 100

# Threshold: all-or-nothing
mode: threshold
threshold: 0.5
points: 100

# Tiered: stepped milestones
mode: tiered
tiers:
  - above: 0.3, points: 25
  - above: 0.6, points: 50
  - above: 0.9, points: 100
```

An optional `baseline` field can be included in any mode to show a reference line on charts (e.g., the score of a naive/trivial solution).

### Where Scoring is Evaluated

**Server-side, in core logic.** The server applies the scoring policy when serving the submissions API. Reasons:

- **Authoritative ranking** — no client-side inconsistencies.
- **Retroactive changes** — changing a policy recomputes on the fly since raw scores are stored, not transformed ones.
- **Single source of truth** — one evaluation function in `ref/core/`.

### Badges

Badges are a **visual consequence of scoring**, not a separate system. When a team earns points for a challenge (i.e., crosses a threshold or achieves a score), the frontend renders a badge icon. Badge assets are static files per exercise name (`/static/badges/<name>.svg`) with a default fallback. No extra backend logic is needed — the frontend derives badges from the scoring data.

## Integration Plan

### 1. `ExerciseConfig` Model and Migration

Create the `ExerciseConfig` model. Migrate existing administrative fields (`category`, deadlines, `submission_test_enabled`, `max_grading_points`) from `Exercise` rows into `ExerciseConfig` rows. Add `scoring_policy` JSON column. Update `Exercise` with a FK `config_id` pointing to `ExerciseConfig`.

The migration:
1. Create `exercise_config` table.
2. Populate it from distinct `short_name` values in `exercise`, taking field values from the head (newest) version.
3. Add `config_id` FK column to `exercise` and backfill it.
4. (Optional, later) Drop the migrated columns from `exercise`.

### 2. Update ExerciseManager

- On first import: create `ExerciseConfig` from YAML values.
- On reimport: look up existing `ExerciseConfig` by `short_name`, skip administrative fields from YAML.
- Remove the deadline sync logic from `check_global_constraints()`.

### 3. Scoring API Endpoints

**`GET /api/scoreboard/config`** — Returns exercise metadata grouped by `category` (assignment), including the scoring policy:

```json
{
  "Assignment 1": {
    "exercise_name": {
      "start": "...",
      "end": "...",
      "scoring": {
        "mode": "threshold",
        "threshold": 0.5,
        "points": 100,
        "baseline": 0.013
      }
    }
  }
}
```

**`GET /api/submissions`** — Returns transformed submission scores grouped by exercise and team/user:

```json
{
  "exercise_name": {
    "Team A": [[timestamp, score], ...]
  }
}
```

Scores returned here are already transformed by the server using the exercise's scoring policy.

Both endpoints are rate-limited and publicly accessible (no auth required).

### 4. Exercise Edit UI

Add an edit button to the exercise list page. The edit form modifies `ExerciseConfig` fields:

- Category / assignment
- Deadlines
- Scoring policy (mode dropdown + dynamic fields per mode)
- Max grading points
- Submission test toggle

### 5. Scoreboard Frontend

Add a scoreboard page at `/scoreboard`:

- Fetches `/api/scoreboard/config` and `/api/submissions` periodically.
- Renders a **ranking table** (sorted by total points) with **badge icons** for earned challenges.
- Renders **per-challenge score charts** using Chart.js with baseline annotation lines.
- Shows a **countdown timer** for the active assignment's deadline.
- Supports multiple assignments via tab navigation.
- Fully dynamic — number of assignments and challenges driven by API data.

The `raid/raid` JS can be reused but should be refactored to remove the hardcoded 3x3 layout.

### 6. System Settings

| Setting | Type | Purpose |
|---------|------|---------|
| `SCOREBOARD_ENABLED` | bool | Toggle scoreboard visibility |
| `LANDING_PAGE` | str | Choose default student landing page (registration / scoreboard) |

## Key Design Decisions (to be made)

- **Public vs. authenticated scoreboard**: Should the scoreboard require login? The `raid/raid` version is public.
- **Score aggregation**: Should ranking use sum of best scores per challenge, or sum of all earned points? The prototype sums badge points.
- **Polling interval**: The prototype polls every 5 seconds. Consider server-side caching or a longer interval.
- **Admin scoreboard controls**: Should admins be able to freeze/reset the scoreboard?
- **Dropping old columns**: When to remove the migrated fields from `Exercise` (can be deferred to avoid a big-bang migration).

## Files to Create/Modify

| File | Action |
|------|--------|
| `webapp/ref/model/exercise_config.py` | New: `ExerciseConfig` model |
| `webapp/ref/model/exercise.py` | Add `config_id` FK, remove migrated fields (later) |
| `webapp/ref/core/exercise.py` | Update import logic to use `ExerciseConfig` |
| `webapp/ref/core/scoring.py` | New: `apply_scoring()` helper |
| `webapp/ref/view/api.py` | Add `/api/scoreboard/config` and `/api/submissions` endpoints |
| `webapp/ref/view/exercise.py` | Add edit endpoint for `ExerciseConfig` |
| `webapp/ref/templates/exercise_edit.html` | New: edit form template |
| `webapp/ref/view/student.py` | Add scoreboard route |
| `webapp/ref/templates/student_scoreboard.html` | New template |
| `webapp/ref/static/js/scoreboard.js` | Adapt from `raid/raid` |
| `webapp/ref/static/js/plots.js` | Adapt from `raid/raid` (Chart.js plots) |
| `webapp/ref/static/js/utils.js` | Adapt from `raid/raid` (scoring logic) |
| `webapp/ref/static/badges/` | Badge SVG assets (per exercise + default) |
| `webapp/ref/model/settings.py` | Add `SCOREBOARD_ENABLED`, `LANDING_PAGE` |
| `webapp/ref/view/system_settings.py` | Expose new settings in admin UI |
| `migrations/versions/xxx_exercise_config.py` | DB migration |
