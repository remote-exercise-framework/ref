# REF Architecture

Remote Exercise Framework - A platform for hosting programming exercises with isolated student environments.

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         HOST SYSTEM                             │
├─────────────────────────────────────────────────────────────────┤
│  Port 2222 ──> ssh-reverse-proxy (Rust) ──> Instance (SSH)      │
│  Port 8000 ──> web (Flask) ──> Docker API ──> Instance Mgmt     │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Web Application (`webapp/`)

Flask application providing the management interface.

**Stack:** Flask + Jinja2 + Bootstrap + Ace Editor + PostgreSQL

**Key modules:**

- `ref/view/` - Route handlers
  - `api.py` - SSH proxy authentication, provisioning, instance introspection, submissions
  - `exercise.py` - Exercise import, build, delete, toggle defaults
  - `file_browser.py` - Interactive file browser with load/save
  - `grading.py` - Submission grading with search
  - `graph.py` - Network topology visualization
  - `group.py` - User group management
  - `instances.py` - Instance lifecycle (create/start/stop/delete/review/submit)
  - `login.py` - Authentication
  - `student.py` - User management and SSH key generation/restoration
  - `submission.py` - Submission history
  - `system.py` - Garbage collection for dangling containers/networks
  - `system_settings.py` - System configuration (general, group, SSH settings)
  - `visualization.py` - Analytics dashboards (submission trends, container graphs)

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
| `web-host` | `br-whost-ref` | External | Web ↔ Host (HTTP access) |
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
./ctrl.sh up --hot-reloading     # Start with hot reloading
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
