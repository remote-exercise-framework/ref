# REF Architecture

Remote Exercise Framework - A platform for hosting programming exercises with isolated student environments.

## System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                            HOST SYSTEM                               │
├──────────────────────────────────────────────────────────────────────┤
│  ssh_host_port ──> ssh-reverse-proxy (Rust) ──> Instance (SSH)       │
│  http(s)_host_port ──> frontend-proxy (Caddy) ──┬─> web (Flask)      │
│                                                 ├─> spa-frontend     │
│                                                 └─> baked SPA dist/  │
└──────────────────────────────────────────────────────────────────────┘
```

The `frontend-proxy` Caddy container serves HTTP and/or HTTPS (depending
on `tls.mode` in `settings.yaml`) and routes traffic by URL prefix:

- `/spa/*` — the Vue SPA. In dev (`--hot-reloading`) proxied to the
  `spa-frontend` container running `vite dev` with HMR; in prod served as
  a static bundle baked into the frontend-proxy image at build time via a
  multi-stage Dockerfile.
- `/static/*` — Flask's own static assets (bootstrap, ace-builds, favicon,
  etc.), served directly by Caddy from a read-only bind-mount of
  `webapp/ref/static/`.
- Everything else (`/`, `/admin/*`, `/api/*`, `/student/*`) — reverse-proxied
  to the Flask `web` container on the internal `web-host` network.

The `ssh-reverse-proxy` calls `http://web:8000` over the internal
`web-and-ssh` network and does **not** go through Caddy.

## Components

### 1. Web Application (`webapp/`)

Flask application providing the management interface.

**Stack:** Flask + Jinja2 + Bootstrap + Ace Editor + PostgreSQL

**Key modules:**

- `ref/view/` - HTML route handlers (admin + student dashboards)
  - `build_status.py` - `/api/build-status` poll used by the exercises admin UI
  - `exercise.py` - Exercise import, build, delete, toggle defaults
  - `file_browser.py` - Interactive file browser with load/save
  - `grading.py` - Submission grading with search
  - `graph.py` - Network topology visualization
  - `group.py` - User group management
  - `instances.py` - Instance lifecycle (create/start/stop/delete/review/submit)
  - `login.py` - Authentication
  - `student.py` - Admin user management + signed key download endpoints; root/`/` redirect to the SPA landing pages
  - `submission.py` - Submission history
  - `system.py` - Garbage collection for dangling containers/networks
  - `system_settings.py` - System configuration (general, group, SSH settings)
  - `visualization.py` - Analytics dashboards (submission trends, container graphs)

- `ref/services_api/` - JSON endpoints called by other services (not browsers)
  - `ssh.py` - SSH reverse-proxy hooks: `/api/ssh-authenticated`, `/api/provision`, `/api/getkeys`, `/api/getuserinfo`, `/api/header`
  - `instance.py` - Student container callbacks (HMAC-signed with per-instance keys): `/api/instance/reset`, `/api/instance/submit`, `/api/instance/info`

- `ref/frontend_api/` - JSON endpoints consumed by the Vue SPA (`/api/v2/*` + scoreboard)
  - `students.py` - `/api/v2/registration{,/meta}`, `/api/v2/restore-key`
  - `scoreboard.py` - `/api/scoreboard/config`, `/api/scoreboard/submissions`

- `ref/model/` - SQLAlchemy models
  - `user.py` - `User`, `UserGroup`
  - `exercise.py` - `Exercise`, `ExerciseService`, `ExerciseEntryService`, `RessourceLimits`
  - `instance.py` - `Instance`, `InstanceService`, `InstanceEntryService`, `Submission`, `SubmissionTestResult`, `SubmissionExtendedTestResult`, `Grading`
  - `settings.py` - `SystemSetting`, `SystemSettingsManager`
  - `enums.py` - `ExerciseBuildStatus`, `CourseOfStudies`, `UserAuthorizationGroups`

- `ref/core/` - Business logic managers
  - `docker.py` - `DockerClient` for Docker API operations
  - `exercise.py` - `ExerciseManager` for exercise lifecycle and config parsing
  - `instance.py` - `InstanceManager` for container management and submission testing
  - `image.py` - `ExerciseImageManager` for Docker image building
  - `user.py` - `UserManager` for user account management
  - `security.py` - Permission decorators and security utilities
  - `logging.py` - Logging configuration
  - `flash.py` - Flash message utilities
  - `error.py` - `InconsistentStateError` exception
  - `util.py` - `AnsiColorUtil`, `DatabaseLockTimeoutError`, database mixins

**Additional features:**
- Rate limiting via `flask-limiter` (32 req/sec default)
- Database migrations via Flask-Migrate
- Maintenance mode
- Response caching control

### 2. Instance Container (`ref-docker-base/`)

Isolated Docker container per student/exercise based on Ubuntu 24.04.

**Includes:**
- Build tools: `gcc`, `g++`, `clang`, `make`, `nasm`
- Debugging: `gdb` (with `gef`), `valgrind`, `strace`
- Python: `python3`, `pip`, `uv`, `coverage`
- Editors: `vim`, `neovim`, `nano`
- Tools: `tmux`, `screen`, `git`, `curl`, `wget`, `socat`, `netcat`, `htop`

**Security constraints:**
- Limited capabilities: `SYS_CHROOT, SETUID, SETGID, CHOWN, DAC_OVERRIDE, AUDIT_WRITE`
- Resources: 0.5 CPU, 256MB RAM, 512 max PIDs
- Non-root user `user` (uid 9999) for student work
- Overlay filesystem for persistence
- Containers run under `ref-instances.slice` cgroup

**Key container scripts:**
- `task` / `_task` - Submission testing wrapper (C binary + Python implementation)
- `reset-env` - Container environment reset
- `sitecustomize.py` - Coverage collection via `/shared` directory

**Entry point:** SSH server on port 13370

### 2b. Frontend Proxy (`frontend-proxy/`)

Caddy-based reverse proxy container that serves the web interface over
HTTP and/or HTTPS depending on `tls.mode` in `settings.yaml`. Built from
a multi-stage Dockerfile that compiles the SPA bundle (stage 1:
`node:22-alpine`, `npm run build`) and copies it into a
`caddy:2.8-alpine` runtime image (stage 2) along with Python 3 and
Jinja2.

At container start, `entrypoint.sh` either uses `Caddyfile.dev` (for
`--hot-reloading`) or calls `render_caddyfile.py` which renders
`Caddyfile.prod.j2` into a Caddyfile based on `TLS_MODE`, `DOMAIN`, and
`HTTPS_HOST_PORT` environment variables passed from docker-compose.

**TLS modes** (set via `tls.mode` in `settings.yaml`):

| Mode | Container ports | Description |
|------|-----------------|-------------|
| `off` | `:8000` (HTTP) | Plain HTTP, no TLS. |
| `internal` | `:8443` (HTTPS) + `:8080` (HTTP) | Self-signed certificate generated by Caddy. Both ports serve the full site independently; the HTTP port does not redirect to HTTPS by default. Accessible by domain name and by IP address. |
| `acme` | `:443` (HTTPS) + `:80` (HTTP) | Let's Encrypt certificate via ACME. Caddy handles provisioning and renewal automatically. HTTP redirects to HTTPS. |

A `caddy-data` Docker volume persists Caddy's certificate storage across
container restarts (essential for `acme` mode to avoid hitting Let's
Encrypt rate limits).

**Stack:** Caddy 2 + Python 3 / Jinja2 + multi-stage Node builder

**Key files:**
- `Dockerfile` — multi-stage SPA build + Caddy runtime with Python/Jinja2
- `Caddyfile.dev` — dev routing (proxies `/spa/*` to vite dev)
- `Caddyfile.prod.j2` — Jinja2 template rendered at container start per TLS mode
- `Caddyfile.routes` — shared routing directives imported by all prod configs
- `render_caddyfile.py` — renders the Jinja2 template from environment variables
- `entrypoint.sh` — selects dev config or renders prod config, then starts Caddy

**Notes:**
- The Flask rate limiter reads `X-Tinyproxy` to key on the real client IP;
  Caddy sets this header via `header_up X-Tinyproxy {remote_host}` on the
  reverse-proxy path.
- Flask static assets (`/static/*`) are served directly by Caddy with a 1h
  cache header, skipping uWSGI.
- SPA hashed assets (`/spa/assets/*`) are served with
  `public, max-age=31536000, immutable`; `index.html` is `no-cache` so
  deploys are picked up atomically.
- `/admin` and `/admin/` 302-redirect to `/admin/exercise/view`.
- `/spa` 308-redirects to `/spa/` so bare URLs get a trailing slash.

**Dev-mode security warning:**

`./ctrl.sh up --hot-reloading` is a **local-development-only** flag.
When it is set:

1. The `spa-frontend` container is started (gated behind the `dev`
   compose profile) and runs `vite dev` with HMR.
2. `frontend-proxy` selects `Caddyfile.dev` and reverse-proxies
   `/spa/*` (including the HMR websocket) to `spa-frontend:5173`
   without any auth or IP filter.
3. `vite dev` serves raw, unbundled source files and exposes a
   `/@fs/` endpoint. Vite has had several path-traversal CVEs against
   `/@fs/` in recent releases (CVE-2025-30208/31125/31486/32395/46565);
   even on a patched version, the dev server is not designed for
   hostile clients.

**Never run a publicly-reachable REF instance with `--hot-reloading`.**
To make this obvious in the UI, the SPA `DefaultLayout` renders a
hazard-striped warning strip at the very top of every page when
`import.meta.env.DEV` is true; this block is tree-shaken out of the
production `vite build` entirely, so only dev-mode clients ever see
it and the prod bundle contains no trace of the warning code.

### 3. SSH Reverse Proxy (`ssh-reverse-proxy/`)

Rust-based SSH proxy routing student connections to their containers.

**Connection flow:**
1. Client connects: `ssh <exercise>@host -p 2222`
2. Proxy validates key via web API (`/api/getkeys`)
3. Proxy provisions instance via `/api/provision`
4. Traffic proxied directly to container's SSH (port 13370)

**Features:**
- Shell sessions (interactive PTY)
- Command execution (`ssh host command`)
- SFTP subsystem
- Local port forwarding (`-L`)
- Remote port forwarding (`-R`)
- X11 forwarding (`-X`)
- Public key authentication
- HMAC-SHA request signing for API communication

**Stack:** Rust + russh 0.55 + tokio

**Source structure:** `src/main.rs`, `src/server.rs`, `src/api.rs`, `src/config.rs`, `src/channel/` (shell, direct_tcpip, remote_forward, x11, forwarder)

### 4. ref-utils (`ref-docker-base/ref-utils/`)

Python library for exercise submission testing, installed in all containers.

**Modules:** `decorator`, `process`, `assertion`, `utils`, `config`, `serialization`

**Key exports:**
```python
# Test decorators
from ref_utils import add_environment_test, add_submission_test, run_tests

# Process control
from ref_utils import drop_privileges, run, run_capture_output, run_with_payload

# Assertions
from ref_utils import assert_is_file, assert_is_exec

# Output
from ref_utils import print_ok, print_err, print_warn

# Configuration
from ref_utils import Config, get_config, set_config

# Serialization (IPC between task wrapper and submission tests)
from ref_utils import IPCSerializer, safe_dumps, safe_loads
```

### 5. Database

PostgreSQL 17.2 storing:
- Users and groups
- Exercise definitions and services
- Instance state and services
- Submissions, test results, and grades
- System settings

## Docker Networks

| Network | Bridge Name | Type | Purpose |
|---------|-------------|------|---------|
| `web-host` | `br-whost-ref` | External | frontend-proxy ↔ Host, frontend-proxy ↔ web, frontend-proxy ↔ spa-frontend |
| `web-and-ssh` | `br-w2ssh-ref` | Internal | Web ↔ SSH reverse proxy API |
| `web-and-db` | `br-w2db-ref` | Internal | Web ↔ PostgreSQL |
| `ssh-and-host` | `br-shost-ref` | External | SSH reverse proxy ↔ Host |

## Exercise Structure

```
exercises/<name>/
├── settings.yml          # Metadata, deadlines, files
├── submission_tests      # Python tests with @add_submission_test
└── <source files>        # Templates, Makefiles, etc.
```

## Control Script (`ctrl.sh`)

```bash
./ctrl.sh build                  # Build Docker images
./ctrl.sh up [--debug]           # Start services (--debug attaches with logs)
./ctrl.sh up --maintenance       # Start in maintenance mode
./ctrl.sh up --hot-reloading     # Start with hot reloading (LOCAL DEV ONLY; see warning below)
./ctrl.sh down                   # Stop and remove services
./ctrl.sh stop                   # Stop without removing
./ctrl.sh restart                # Restart all services
./ctrl.sh restart-web            # Restart web service only
./ctrl.sh ps                     # List containers
./ctrl.sh logs [-f]              # View logs
./ctrl.sh flask-cmd <args>       # Run Flask CLI commands
./ctrl.sh db-upgrade             # Run database migrations
```

Pre-flight checks: submodule validation, Docker/cgroup v2 requirements, configuration validation.

When `--hot-reloading` is passed, `ctrl.sh` exports `COMPOSE_PROFILES=dev`
for every compose subcommand. This activates the `dev` compose profile
which is the gate on the `spa-frontend` service — without it, `vite dev`
is not started at all. In prod mode, `ctrl.sh up` unsets
`COMPOSE_PROFILES` so `spa-frontend` stays off; the other commands
(`build`, `down`, `stop`, `ps`, `logs`, …) keep the profile active so
profile-gated services can still be built and cleaned up.

> **SECURITY — do not run `--hot-reloading` on a publicly reachable
> host.** The flag starts Vite's dev server behind Caddy with no auth,
> serving raw source over `/spa/*` (including the `/@fs/` endpoint,
> which has had repeated path-traversal CVEs). The SPA itself renders
> a hazard-striped warning strip at the top of every page in this mode
> as a visible reminder. Intended for local development only.

## Test Structure

```
tests/
├── unit/           # Unit tests (no REF instance needed)
├── integration/    # Integration tests (require running REF)
├── e2e/            # End-to-end tests (full system)
├── helpers/        # Test utilities (web_client, ssh_client, exercise_factory, etc.)
├── fixtures/       # Pytest fixtures
├── api/            # API testing utilities
├── conftest.py     # Main pytest configuration
└── summarize_logs.py  # Failure log summary generator
```

## CI

GitHub Actions workflow (`.github/workflows/ci.yml`) runs linting (`ruff check`, `ruff format --check`), type checking (`mypy`), and the test suite.

## Data Persistence

- `/data/postgresql-db/` - Database files
- `/data/data/imported_exercises/` - Exercise definitions
- `/data/data/persistance/` - User submissions and instance data
- `/data/ssh-proxy/` - SSH proxy state
- `/data/log/` - Application logs
