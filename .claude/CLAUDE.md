# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Important Documents

- `README.md` - Project overview and setup instructions
- `EXERCISES.md` - Exercise creation and submission testing
- `docs/ARCHITECTURE.md` - System architecture and components

## Build and Run Commands

```bash
# Build all Docker images
./ctrl.sh build

# Start services (--debug attaches to terminal with logs)
./ctrl.sh up --debug
./ctrl.sh up

# Stop services
./ctrl.sh stop              # Keep containers
./ctrl.sh down              # Remove containers

# Database migrations
./ctrl.sh flask-cmd db upgrade

# View logs
./ctrl.sh logs -f
```

## Code Quality

Python code must be checked using `pyright`, `ruff`, and `mypy`. Install these tools via `uv` if not already installed.

```bash
# From tests/ directory (has pyright config)
cd tests && pyright

# Linting
ruff check .
ruff format .

# Type checking
mypy .
```

**Always run linting and type checking for new code**, in addition to running tests.

## Testing

```bash
# Install test dependencies
cd tests && uv sync

# Run all tests (requires running REF instance)
cd tests && pytest

# Run only unit tests
cd tests && pytest unit/

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

## Dependency Management

Use `uv` for all Python dependency management. Each component has its own `pyproject.toml`:
- `webapp/pyproject.toml` - Web application
- `ssh-wrapper/pyproject.toml` - SSH wrapper
- `ref-docker-base/pyproject.toml` - Container base image
- `tests/pyproject.toml` - Test suite

## Architecture Overview

REF is a containerized platform for hosting programming exercises with isolated student environments.

### Components

1. **Web Application** (`webapp/`) - Flask app on port 8000
   - `ref/view/` - Route handlers
   - `ref/model/` - SQLAlchemy models
   - `ref/core/` - Docker operations, exercise building, instance management

2. **SSH Entry Server** (`ssh-wrapper/`) - Custom OpenSSH on port 2222
   - Routes student SSH connections to exercise containers
   - Uses web API for authentication and provisioning

3. **Instance Container** (`ref-docker-base/`) - Ubuntu 24.04 with dev tools
   - Isolated per student/exercise
   - SSH server on port 13370
   - Contains `ref-utils` for submission testing

4. **Database** - PostgreSQL storing users, exercises, instances, submissions

### Connection Flow

```
Client (ssh exercise@host -p 2222)
  -> sshserver validates via /api/getkeys
  -> ssh-wrapper provisions via /api/provision
  -> Traffic proxied to container SSH (port 13370)
```

### Data Persistence

- `/data/postgresql-db/` - Database files
- `/data/data/imported_exercises/` - Exercise definitions
- `/data/data/persistance/` - User submissions and instance data
- `/data/log/` - Application logs

## Commit Messages

- Do not include Claude as author or co-author in commit messages.
- Do not include historical context like "this fixes the failing test" or "this addresses the previous issue". Describe what the change does, not why it was needed.
