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

### 1. Web Frontend (`webapp/`)

Flask application providing the management interface.

**Stack:** Flask + Jinja2 + Bootstrap + Ace Editor + PostgreSQL + Redis

**Key modules:**
- `ref/view/` - Route handlers (login, exercises, instances, grading, API)
- `ref/model/` - SQLAlchemy models (users, exercises, instances)
- `ref/core/` - Business logic (Docker operations, exercise building)

**Features:**
- Exercise management and import
- Instance lifecycle (create/start/stop/delete)
- File browser and code editor
- Submission grading interface
- Network visualization

### 2. Instance Container (`ref-docker-base/`)

Isolated Docker container per student/exercise based on Ubuntu 24.04.

**Includes:** GCC, Clang, Python3, GDB, Valgrind, SSH server, editors (vim/nano/neovim), tmux

**Security constraints:**
- Limited capabilities: `SYS_CHROOT, SETUID, SETGID, CHOWN, DAC_OVERRIDE, AUDIT_WRITE`
- Resources: 0.5 CPU, 256MB RAM, 512 max PIDs
- Non-root user `user` (uid 9999) for student work
- Overlay filesystem for persistence

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

**Stack:** Rust + russh + tokio

### 4. ref-utils (`ref-docker-base/ref-utils/`)

Python library for exercise submission testing, installed in all containers.

**Key functions:**
```python
from ref_utils.decorator import add_submission_test, run_tests
from ref_utils.process import run, run_capture_output, drop_privileges
from ref_utils.assertion import assert_is_file, assert_is_exec
from ref_utils.utils import print_ok, print_err, print_warn
from ref_utils.checks import run_pylint, run_mypy, contains_flag
```

### 5. Database

PostgreSQL 17.2 storing:
- Users and groups
- Exercise definitions
- Instance state and services
- Submissions and grades

## Docker Networks

| Network | Purpose |
|---------|---------|
| `web-and-ssh` | Web ↔ SSH reverse proxy API |
| `web-and-db` | Web ↔ PostgreSQL |
| `ssh-and-host` | SSH reverse proxy ↔ Host |

## Exercise Structure

```
exercises/<name>/
├── settings.yml          # Metadata, deadlines, files
├── submission_tests      # Python tests with @add_submission_test
└── <source files>        # Templates, Makefiles, etc.
```

## Control Script

```bash
./ctrl.sh build    # Build Docker images
./ctrl.sh up       # Start services
./ctrl.sh down     # Stop services
./ctrl.sh flask-cmd db upgrade  # Run migrations
```

## Data Persistence

- `/data/postgresql-db/` - Database files
- `/data/data/imported_exercises/` - Exercise definitions
- `/data/data/persistance/` - User submissions
- `/data/log/` - Application logs
