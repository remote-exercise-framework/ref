# Configuration

This document describes how REF's bootstrap configuration is generated, stored,
and consumed. It covers the first-run flow, the three generated files, how to
change settings after the initial install, and the subtle interactions between
`ctrl.sh` and `docker compose`.

For in-app runtime settings that administrators edit through the web UI (group
configuration, SSH settings, maintenance banner, etc.), see
`webapp/ref/model/system_settings.py` and `SystemSettingsManager`. Those are a
separate layer and live in the database, not on disk.

## Overview

REF's bootstrap configuration has one canonical source and two derived
artifacts:

```
settings.yaml  (canonical, hand-editable, contains secrets)
     |
     v  prepare.py renders
     |
     +---> settings.env          (consumed by docker compose --env-file)
     |
     +---> docker-compose.yml    (rendered from docker-compose.template.yml
                                  via jinja; references ${VAR} placeholders
                                  that resolve against the shell env or
                                  settings.env at runtime)
```

All three files plus `container-keys/root_key` and `container-keys/user_key`
are produced on a fresh checkout by `./prepare.py`. All three are gitignored
(`settings.yaml`, `settings.env`, `docker-compose.yml`), and `settings.yaml` /
`settings.env` are written with mode `0600` because they contain plaintext
secrets.

## Running `prepare.py`

`prepare.py` has two modes:

- **Bootstrap** (no `settings.yaml`): generates cryptographically secure
  secrets (`admin.password`, `secrets.secret_key`, `secrets.ssh_to_web_key`,
  `secrets.postgres_password` — 32 bytes each via `secrets.token_urlsafe`),
  auto-detects the host's docker group ID (`getent group docker`, fallback
  `999`), writes `settings.yaml` (mode `0600`), and then renders the
  downstream files. Prints the generated admin password to stdout.
- **Re-render** (`settings.yaml` already exists): loads the existing yaml and
  re-renders `settings.env`, `docker-compose.yml`, and the SSH host keys
  from it. Secrets are not touched. This is the mode you want for routine
  config edits (see "Changing configuration" below).

Pass `--fresh` to force bootstrap mode even when `settings.yaml` exists. The
existing file is moved to `settings.yaml.backup` first so the previous
secrets can be recovered if needed.

Downstream rendering steps (run in both modes):

1. `render_settings_env()` writes `settings.env` from the yaml.
2. `generate_docker_compose()` renders `docker-compose.yml` from
   `docker-compose.template.yml` via jinja, threading `paths.*` and
   `runtime.*` values from the yaml through as template variables. Production
   cgroup slice names (`ref-core.slice`, `ref-instances.slice`) and
   `testing=False` / `bridge_id=""` are the only values still hard-coded in
   `prepare.py`.
3. `generate_ssh_keys()` creates ed25519 SSH host keys in `container-keys/`
   if missing (existing keys are left alone) and mirrors them into
   `ref-docker-base/container-keys/` for the base image build.

`ctrl.sh` handles the first-run case automatically: if neither
`settings.yaml` nor `settings.env` exists, it invokes `./prepare.py` before
running any docker-compose command. If exactly one of them exists, or if
`docker-compose.yml` / `container-keys/*` are missing, it errors out and
asks the operator to re-run `prepare.py` or `prepare.py --fresh`.

## The three files

### `settings.yaml` — canonical configuration

The only file you should edit by hand. Structure:

```yaml
docker_group_id: 999
ports:
  ssh_host_port: 2222
  http_host_port: 8000
paths:
  data: ./data                             # bind-mounted into web as /data
  exercises: ./exercises                   # bind-mounted into web as /exercises
  ref_utils: ./ref-docker-base/ref-utils   # bind-mounted read-only as /ref-utils
runtime:
  binfmt_support: false    # if true, renders the foreign-arch-runner service
admin:
  password: <random 32-byte url-safe secret>
  ssh_key: null          # if null, web app generates one on first boot
secrets:
  secret_key: <random>          # Flask session / CSRF signing key
  ssh_to_web_key: <random>      # HMAC shared between SSH proxy and web API
  postgres_password: <random>   # Postgres superuser password
```

Field semantics:

- `docker_group_id` — must match the host's `docker` group (`getent group
  docker`); `ctrl.sh` fails fast if they diverge.
- `ports.ssh_host_port` / `ports.http_host_port` — host ports published by
  the `ssh-reverse-proxy` and `web` services respectively.
- `paths.*` — on-host paths that get bind-mounted into the web container.
  Changing these requires re-running `./prepare.py` and then
  `./ctrl.sh restart` (the paths are compiled into `docker-compose.yml` at
  render time).
- `runtime.binfmt_support` — if `true`, `prepare.py` renders a
  `foreign-arch-runner` service into `docker-compose.yml` that installs
  `qemu-user-static` for running foreign-architecture binaries. Leave
  `false` unless you actually need it.
- `admin.password` — first-login password for admin user `0`.
- `admin.ssh_key` — optional. If `null`, the web app generates a keypair on
  first boot and exposes the private key through the admin web interface.
- `secrets.*` — three independent random secrets. They can be rotated
  individually (see "Rotating secrets" below).

### `settings.env` — derived, consumed by docker compose

Auto-generated artifact. Do not edit by hand — your changes will be lost the
next time `prepare.py` runs. The file carries a header warning to that effect.

Variables rendered from the yaml:

| Variable            | Source                                 | Required |
|---------------------|----------------------------------------|----------|
| `ADMIN_PASSWORD`    | `admin.password`                       | yes      |
| `ADMIN_SSH_KEY`     | `admin.ssh_key` (empty string if null) | no       |
| `DOCKER_GROUP_ID`   | `docker_group_id`                      | yes      |
| `SSH_HOST_PORT`     | `ports.ssh_host_port`                  | yes      |
| `HTTP_HOST_PORT`    | `ports.http_host_port`                 | yes      |
| `SECRET_KEY`        | `secrets.secret_key`                   | yes      |
| `SSH_TO_WEB_KEY`    | `secrets.ssh_to_web_key`               | yes      |
| `POSTGRES_PASSWORD` | `secrets.postgres_password`            | yes      |

"Required" means `ctrl.sh` refuses to start if the value is empty, and the
compose template uses the `${VAR:?message}` form that causes `docker compose`
itself to fail with a clear error. `DEBUG` and `MAINTENANCE_ENABLED` are
**not** in `settings.env` — they default to `0` in the compose template and
are only flipped on by `ctrl.sh up` based on its `--debug` / `--maintenance`
CLI flags.

### `docker-compose.yml` — derived, consumed by docker compose

Rendered by `prepare.py` from `docker-compose.template.yml` using jinja. The
template variables are fixed in `prepare.py` for the production flow
(`data_path=./data`, `exercises_path=./exercises`, production cgroup names),
so regenerating does not normally change the output unless the template
itself changes.

The rendered compose file is the only file docker compose actually reads.
Variables in the template fall into two classes:

- **Jinja template variables** (`{{ cgroup_parent }}`, `{{ data_path }}`,
  `{% if testing %}`, …) — resolved at render time by `prepare.py`. To
  change these you must edit `prepare.py` and re-render.
- **Compose interpolation variables** (`${POSTGRES_PASSWORD}`, `${DEBUG}`,
  …) — resolved at `docker compose` runtime. These either come from the
  shell environment or from `settings.env` (via `--env-file`).

## Runtime data flow

`ctrl.sh` is the production entrypoint. For every command that touches docker
compose, it does three things:

1. Sources `settings.env` into its own shell so it can run pre-flight checks:
   docker group ID match, required values non-empty, docker daemon address
   pool sanity (`ctrl.sh:256`).
2. For the `up` command specifically, exports runtime toggles
   (`REAL_HOSTNAME`, `DEBUG`, `MAINTENANCE_ENABLED`, `DISABLE_TELEGRAM`,
   `DEBUG_TOOLBAR`, `HOT_RELOADING`, `DISABLE_RESPONSE_CACHING`) based on
   CLI flags.
3. Invokes `docker compose -p ref --env-file settings.env <cmd>`. Docker
   compose then resolves every `${VAR}` placeholder in `docker-compose.yml`
   against: **shell environment first, then `--env-file` values, then the
   defaults written into the compose template**.

The runtime dev/debug flags in the compose template (`DEBUG`,
`MAINTENANCE_ENABLED`, `DISABLE_TELEGRAM`, `DEBUG_TOOLBAR`, `HOT_RELOADING`,
`DISABLE_RESPONSE_CACHING`, `RATELIMIT_ENABLED`, `DOCKER_RESSOURCE_PREFIX`,
`REAL_HOSTNAME`) are intentionally **not** in `settings.env`. They default
to `0` / empty in the compose template (via `${VAR:-0}` and `${VAR}`) and
are only flipped on when `ctrl.sh up` exports them based on its CLI flags.
Any command that doesn't export them (`build`, `restart`, `logs`, …)
therefore gets the template defaults.

## Changing configuration

### Routine config edits

`settings.yaml` is the canonical file — edit it and re-run `./prepare.py` to
propagate the changes into `settings.env` and `docker-compose.yml`. Then
restart the affected services with `./ctrl.sh restart` (or
`./ctrl.sh restart-web` if only the web container needs to pick up the
change).

```bash
$EDITOR settings.yaml     # e.g. change ports.ssh_host_port to 2223
./prepare.py              # re-renders settings.env + docker-compose.yml
./ctrl.sh restart
```

Re-running is safe: `prepare.py` loads the existing yaml, never touches the
secrets, and the SSH host key generation step skips keys that already exist.
`settings.env` and `docker-compose.yml` are overwritten from the yaml on
every run.

### Rotating secrets

To rotate a single secret (e.g. `SECRET_KEY`):

1. Generate a new value: `python3 -c "import secrets;
   print(secrets.token_urlsafe(32))"`
2. Paste it into `settings.yaml` under `secrets:`.
3. Re-run `./prepare.py` and then `./ctrl.sh restart`.

Secret-specific notes:

- `postgres_password` — Postgres sets the password when the data directory is
  first initialised. Rotating after initialisation requires also updating the
  password inside Postgres (e.g. via `ALTER USER ref PASSWORD '...'`)
  otherwise the web app will fail to connect. Do this before updating
  `settings.yaml`.
- `ssh_to_web_key` — shared between the web API and the SSH reverse proxy.
  Both containers must restart together for the new key to take effect;
  `./ctrl.sh restart` is the correct command.
- `secret_key` — Flask session / CSRF signing key. Rotating invalidates all
  existing user sessions.
- `admin.password` — used only for the initial admin user creation. After
  the admin exists, rotating this value has no effect; change the password
  through the web UI instead.

To rotate **every** secret at once, run `./prepare.py --fresh`. This moves
the existing `settings.yaml` to `settings.yaml.backup`, generates fresh
secrets, and re-renders everything. You must then either reset
`postgres_password` inside Postgres or wipe `data/postgresql-db/` and
re-initialise the database.

## Test harness

The test suite in `tests/helpers/ref_instance.py` does not use the repo's
`settings.yaml` or `settings.env`. Each test instance generates its own
`settings.env` via `RefInstance._generate_settings_env()` into a per-test
work directory, with a test-specific `DOCKER_RESSOURCE_PREFIX` so that
parallel instances do not clash. It also renders its own `docker-compose.yml`
via `_generate_docker_compose()` with `testing=True`, which skips the host
port mappings (tests allocate ephemeral ports) and injects per-test cgroup
slice names and bridge names.

The upshot: editing the repo's `settings.yaml` or `settings.env` has no
effect on the test suite. Test behaviour is controlled by the `RefInstance`
config dataclass.

## Gotchas

- **`settings.env` is not automatically loaded by `docker compose` alone.**
  It only takes effect because `ctrl.sh` passes `--env-file settings.env`.
  If you run `docker compose` directly from the repo root without that
  flag, compose falls back to its default `.env` lookup, finds nothing, and
  every `${VAR:?...}` placeholder fails. Always go through `ctrl.sh`, or
  replicate its `--env-file` / shell-export pattern manually.
- **`container-keys/` and `ref-docker-base/container-keys/` must stay in
  sync.** `prepare.py` copies the former into the latter so the base image
  build picks them up. If you rotate the host keys, re-run `./prepare.py`
  or rebuild the base image.
- **`settings.yaml` and `settings.env` are mode `0600` by design.** Do not
  loosen the permissions — they contain plaintext secrets.
