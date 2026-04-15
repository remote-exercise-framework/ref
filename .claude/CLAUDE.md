# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Important Documents

- `README.md` - Project overview and setup instructions
- `EXERCISES.md` - Exercise creation and submission testing
- `docs/ARCHITECTURE.md` - System architecture and components
- `.claude/CONTEXT.md` - Ongoing work and recent changes (create if missing)

## Build and Run Commands

**Note:** In sandboxed environments where `~/.docker` may be read-only, set `DOCKER_CONFIG` to a writable directory before running Docker commands:

```bash
export DOCKER_CONFIG=/path/to/repo/.docker-cache
```

The test infrastructure (`tests/helpers/ref_instance.py`) automatically sets this to `.docker-cache/` in the repo root.

```bash
# Build all Docker images
./ctrl.sh build

# Start services
# For development, always use --debug and --hot-reloading:
#   --debug         enables Flask debug mode and verbose logging
#   --hot-reloading enables Flask auto-reload and runs the spa-frontend
#                   under `vite dev` (Vite HMR) instead of a static build
./ctrl.sh up --debug --hot-reloading
./ctrl.sh up                            # production-style start, no HMR

# Stop services
./ctrl.sh stop              # Keep containers
./ctrl.sh down              # Remove containers

# Database migrations
./ctrl.sh db-upgrade

# View logs
./ctrl.sh logs -f
```

## Code Quality

Python code must pass the same checks as CI. **Always run these checks on new or modified code.**

```bash
# Install tools (if needed)
uv tool install ruff
uv tool install mypy

# Install test dependencies (required for mypy)
cd tests && uv sync

# Linting and formatting (run from repo root)
ruff check .
ruff format --check .    # Verify formatting (use 'ruff format .' to fix)

# Type checking (run from tests/ directory)
cd tests && uv run mypy .
```

These checks must pass before committing. CI will reject PRs that fail any of these checks.

### Git Hooks

A pre-commit hook is available that automatically runs linting checks before each commit:

```bash
# Install git hooks
./hooks/install.sh
```

The hook runs `ruff check`, `ruff format --check`, and `mypy`, rejecting commits that fail.

## Testing

**Important:** Never manually start a REF instance for running automated Python tests. The test infrastructure handles instance lifecycle automatically. Starting instances manually for interactive testing/debugging is fine.

```bash
# Install test dependencies
cd tests && uv sync

# Run all tests (test infrastructure manages REF instance)
cd tests && pytest

# Run only unit tests
cd tests && pytest unit/

# Run only integration tests
cd tests && pytest integration/

# Run only E2E tests
cd tests && pytest e2e/

# Skip slow tests
cd tests && pytest -m "not slow"

# Run a single test file
cd tests && pytest unit/test_ssh_client.py

# Run a specific test
cd tests && pytest unit/test_ssh_client.py::test_function_name
```

Tests must fail if dependencies are missing. Only skip tests if explicitly requested.

**Do not write tests that check CLI help commands.** Testing `--help` output is low value.

**Do not use hardcoded values in assertions.** Tests should verify behavior and relationships, not specific magic numbers or strings that may change.

### Test Architecture and Abstractions

Tests outside of `tests/unit/` (e.g., integration tests, E2E tests) must **never directly manipulate database objects**. Instead, they should:

1. **Use manager classes** - `ExerciseManager`, `InstanceManager`, `ExerciseImageManager` provide the business logic layer
2. **Follow view function patterns** - Replicate the same logic that view functions in `ref/view/` use
3. **Use `tests/helpers/method_exec.py`** - Pre-built functions that call managers via `remote_exec`

This ensures tests exercise the same code paths as the real application, catching integration issues that unit tests might miss.

**Example - Correct approach:**
```python
# Use InstanceManager.remove() like the view does
mgr = InstanceManager(instance)
mgr.remove()
```

**Example - Incorrect approach:**
```python
# Don't directly delete DB objects
db.session.delete(instance)
db.session.commit()
```

The abstraction layers are:
- `ref/view/` - HTTP request handlers (views)
- `ref/core/` - Business logic managers (ExerciseManager, InstanceManager, etc.)
- `ref/model/` - SQLAlchemy models (data layer)

Tests should interact with `ref/core/` managers or replicate `ref/view/` logic, not bypass them to manipulate `ref/model/` directly.

## Dependency Management

Use `uv` for all Python dependency management. Each component has its own `pyproject.toml`:
- `webapp/pyproject.toml` - Web application
- `ref-docker-base/pyproject.toml` - Container base image
- `tests/pyproject.toml` - Test suite

## Architecture Overview

REF is a containerized platform for hosting programming exercises with isolated student environments. See `docs/ARCHITECTURE.md` for full details.

### Components

1. **Web Application** (`webapp/`) - Flask app on port 8000
   - `ref/view/` - HTML route handlers (exercises, grading, instances, file browser, visualization, admin student management, system settings, etc.)
   - `ref/services_api/` - JSON endpoints called by services (SSH reverse proxy hooks in `ssh.py`, student container callbacks in `instance.py`)
   - `ref/frontend_api/` - JSON endpoints consumed by the Vue SPA (registration/restore-key in `students.py`, public scoreboard in `scoreboard.py`; mounted under `/api/v2/*` + `/api/scoreboard/*`)
   - `ref/model/` - SQLAlchemy models (users, groups, exercises, instances, submissions, grades, system settings)
   - `ref/core/` - Business logic managers (`ExerciseManager`, `InstanceManager`, `ExerciseImageManager`, `UserManager`, `DockerClient`, etc.)

   Student-facing pages (registration, restore-key, public scoreboard) are served by the Vue SPA under `/spa/*` and talk to `ref/frontend_api/`. Admin pages live under `ref/view/` as Jinja-rendered HTML. The Caddy `frontend-proxy` container fronts both on a single host port 8000 — it reverse-proxies `/spa/*` to `spa-frontend:5173` (dev, with HMR) or serves a baked SPA bundle (prod), serves Flask's `/static/*` directly, and proxies everything else to `web:8000`.

2. **SSH Reverse Proxy** (`ssh-reverse-proxy/`) - Rust-based SSH proxy on port 2222
   - Routes student SSH connections to exercise containers
   - Uses web API with HMAC-signed requests for authentication and provisioning
   - Supports shell, exec, SFTP, local/remote port forwarding, and X11 forwarding

3. **Instance Container** (`ref-docker-base/`) - Ubuntu 24.04 with dev tools
   - Isolated per student/exercise under `ref-instances.slice` cgroup
   - SSH server on port 13370
   - Contains `ref-utils` for submission testing
   - `task`/`_task` scripts for submission testing, `reset-env` for container reset

4. **Database** - PostgreSQL 17.2 storing users, groups, exercises, instances, submissions, grades, system settings

### Connection Flow

```
Client (ssh exercise@host -p 2222)
  -> ssh-reverse-proxy validates via /api/getkeys
  -> ssh-reverse-proxy provisions via /api/provision
  -> Traffic proxied to container SSH (port 13370)
```

### Docker Networks

- `web-host` - Web ↔ Host (HTTP access)
- `web-and-ssh` - Web ↔ SSH reverse proxy API (internal)
- `web-and-db` - Web ↔ PostgreSQL (internal)
- `ssh-and-host` - SSH reverse proxy ↔ Host

### Data Persistence

- `/data/postgresql-db/` - Database files
- `/data/data/imported_exercises/` - Exercise definitions
- `/data/data/persistance/` - User submissions and instance data
- `/data/ssh-proxy/` - SSH proxy state
- `/data/log/` - Application logs

## Code Comments

- Do not reference line numbers in comments (e.g., "see ssh.py lines 397-404"). Line numbers change frequently and become outdated. Reference functions, classes, or use direct code references instead.

## Pending Tasks

Pending tasks in the codebase are marked with `FIXME(claude)` and `TODO(claude)`. When the user requests to process todos or fixmes, search for these markers and address them.

## Fixing Race Conditions

**Never fix race conditions by:**
- Adding timeouts or delays (e.g., `time.sleep()`)
- Reducing the number of threads or parallel processes
- Reducing test parallelism (e.g., changing `-n 10` to `-n 4`)

These approaches hide the underlying problem rather than fixing it. Race conditions must be fixed by addressing the root cause: proper synchronization, locking, atomic operations, or architectural changes.

## Commit Messages

- Do not include Claude as author or co-author in commit messages.
- Do not include historical context like "this fixes the failing test" or "this addresses the previous issue". Describe what the change does, not why it was needed.

## Test Log Summary

After test failures, a summary is automatically generated at `tests/failure_logs/SUMMARY.txt`. To regenerate manually:

```bash
cd tests && python3 summarize_logs.py
```

**Maintaining the pattern list:** The `ERROR_PATTERNS` dict in `tests/summarize_logs.py` defines which errors are detected. Keep this list accurate:
- **Add patterns** for error types that appear in logs but are missing from the summary
- **Remove patterns** that trigger false positives (matching non-error text)
