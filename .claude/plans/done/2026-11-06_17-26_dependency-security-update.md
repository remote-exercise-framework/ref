# Dependency security update

Created 2026-11-06 17:26

## Goal

Clear as many GitHub Dependabot alerts on `remote-exercise-framework/ref` as
possible by refreshing dependencies, and find out which alerts a refresh
*cannot* clear.

## How the alert list was obtained

The Dependabot page itself is not readable from this machine: it needs a
logged-in GitHub session with write access on the repo, and there is no `gh`
CLI and no browser session here. Playwright (Python) was installed and renders
github.com fine, but the alerts URL returns 404 when unauthenticated.

So the alert list below is **reconstructed locally** with the same advisory
databases Dependabot uses:

- Python: `pip-audit` against `uv export` output for each component
- npm: `npm audit` against `spa-frontend/package-lock.json`
- Rust: `cargo audit` against `ssh-reverse-proxy/Cargo.lock`

This should be close to Dependabot's list but is not guaranteed identical.
After pushing, compare against the real page and fold any difference back in.

## Findings

### Python — a lockfile refresh fixes nearly all of it

Vulnerable packages found, by component:

| Component | Vulnerable packages |
|---|---|
| `webapp` | certifi, cryptography, idna, mako, urllib3, werkzeug |
| `tests` | anyio, certifi, cryptography, idna, mako, paramiko, soupsieve, urllib3, werkzeug |
| `ref-docker-base` | pyjwt, pylint, urllib3 |
| `ref-docker-base/ref-utils` | certifi, idna, urllib3 |

All of these are transitive or range-pinned, so `uv lock --upgrade` moves them,
**except two exact pins that block their own fix**:

- `ref-docker-base/pyproject.toml`: `pyjwt==2.12.1` — needs >= 2.15.0
- `ref-docker-base/pyproject.toml`: `pylint==4.0.5` — needs >= 4.0.9

`cryptography>=46.0.7` in `webapp/pyproject.toml` has advisories fixed in
48.0.1 / 49.0.0 / 50.0.0; the floor is satisfiable by the lock refresh, but the
floor should be raised so a future `uv lock` cannot drop back.

### npm (`spa-frontend`) — a refresh does *not* clear this

22 advisories. Two separate problems:

1. **Far behind on majors.** Several direct deps are one to two majors back:

   | Package | In lock | Latest |
   |---|---|---|
   | vite | 6.4.2 | 8.3.6 |
   | vuetify | 3.12.5 | 4.3.2 |
   | pinia | 2.3.1 | 4.1.0 |
   | vue-router | 4.6.4 | 5.4.0 |
   | @vitejs/plugin-vue | 5.x | 6.0.10 |
   | vue-tsc | 2.2.12 | 3.3.14 |
   | echarts | 6.0.0 | 6.1.0 |

   The `^` ranges in `package.json` cannot cross a major, so `npm update` alone
   will not move them. Each needs a deliberate bump plus a build and a look at
   the SPA.

2. **Some advisories have no published fix at all.** `npm audit` reports
   `fixAvailable: false` for brace-expansion, minimatch, nanoid, postcss,
   @vue/server-renderer, and the vite advisories. Those alerts will still be
   open after any update, and the honest resolution is to dismiss them with a
   reason rather than chase a version that does not exist.

   Worth noting what they actually are: most are denial-of-service in build-time
   tooling (brace-expansion, minimatch, nanoid, source-map-js), and the vite ones
   are dev-server issues plus `launch-editor` problems that only apply on
   Windows. The SPA is built at image-build time and served as static files by
   Caddy in production, so build-time DoS and dev-server advisories do not
   describe a reachable path in a deployed REF. The two that do deserve a real
   look are the `@vue/server-renderer` XSS and the echarts XSS, since echarts
   renders scoreboard data.

### Rust (`ssh-reverse-proxy`) — the most urgent part, and invisible to Dependabot

`.gitignore` has `**/Cargo.lock`, so the lockfile is not committed. Dependabot
needs a committed `Cargo.lock` to produce alerts for a binary crate, which means
the SSH proxy — the one component directly exposed to student traffic on port
2222 — gets no alerts at all. Nothing from this section is on the Dependabot
page, and that is the point.

`cargo audit` finds 8 advisories plus one unmaintained-crate warning:

| Crate | Version | Advisory | Severity | Fixed in |
|---|---|---|---|---|
| russh | 0.55.0 | RUSTSEC-2026-0154, unbounded 32-bit allocation | 7.5 high | 0.60.3 |
| russh-cryptovec | 0.52.0 | RUSTSEC-2026-0153, unchecked `CryptoVec` allocation | 7.5 high | 0.60.3 |
| libcrux-secrets | 0.0.4 | RUSTSEC-2026-0212, bad constant-time swap/select on aarch64 | 8.2 high | 0.0.6 |
| libcrux-sha3 | 0.0.4 | RUSTSEC-2026-0208, panic in AVX2 SHAKE-256 | 8.2 high | 0.0.10 |
| libcrux-sha3 | 0.0.4 | RUSTSEC-2026-0207 + RUSTSEC-2026-0074, wrong incremental SHAKE output | — | 0.0.10 / 0.0.8 |
| crypto-bigint | 0.5.5 | RUSTSEC-2026-0387, timing variability in constant-time ops | — | 0.7.6 |
| rsa | 0.9.10 | RUSTSEC-2023-0071, Marvin timing attack | 5.9 medium | no fix published |
| proc-macro-error2 | 2.0.1 | RUSTSEC-2026-0173, unmaintained | warning | — |

The russh pair matters most: an unbounded allocation reachable from an
unauthenticated SSH handshake is a remote denial of service against the proxy
every student connects through. `russh = "0.55"` in `Cargo.toml` cannot reach
0.60.3 within its range, so this needs an explicit bump and will bring API
changes — russh moved several versions in between. The libcrux and crypto-bigint
entries are russh's own transitive crypto stack and should come along with it.

`rsa`'s Marvin advisory has no fix and never will in the 0.9 line; it is only
reachable if the proxy handles RSA keys, which is worth confirming.

Also a major behind: `thiserror = "1"` (2.x is current) and `rand = "0.8"`,
which the comment says is pinned to match russh — recheck that against whatever
russh version lands.

### Base images and CI actions

Dependabot alerts do not cover Docker base images or GitHub Actions, so these
are not on the page — but they are the same class of staleness and are pinned
old enough to mention:

- `webapp/Dockerfile`: `python:3.13.1-bookworm` — a specific old patch release
- `frontend-proxy/Dockerfile`: `caddy:2.8-alpine`
- `ssh-reverse-proxy/Dockerfile`: `rust:bookworm` + `debian:bookworm-slim` (trixie is current stable)
- `docker-compose.template.yml`: `postgres:17.2`
- `.github/workflows/ci.yml`: `astral-sh/setup-uv@v4` (v7 is current)

## Plan

Ordered so each step can be pushed and judged on its own.

### 1. Python lockfile refresh — the cheap, high-yield step
- [ ] Raise the two blocking pins in `ref-docker-base/pyproject.toml`:
      `pyjwt` to `>=2.15.0`, `pylint` to `>=4.0.9`
- [ ] Raise the `cryptography` floor in `webapp/pyproject.toml` to the fixed version
- [ ] `uv lock --upgrade` in `webapp/`, `tests/`, `ref-docker-base/`,
      `ref-docker-base/ref-utils/`
- [ ] Re-run `pip-audit` on each to confirm it comes back clean
- [ ] `ruff check .`, `ruff format --check .`, `cd tests && uv run mypy .`
- [ ] `./ctrl.sh build` then `cd tests && pytest`
- [ ] Commit and push; check how far the alert count drops

Note `ref-utils` is a git submodule with its own repo, so its lockfile change
has to be committed and pushed there, then the submodule pointer bumped here.

### 2. russh upgrade — do this first if anything is prioritised
- [ ] Bump `russh` from 0.55 to >= 0.60.3 in `ssh-reverse-proxy/Cargo.toml` and
      fix up the API changes across those releases
- [ ] Recheck whether `rand = "0.8"` is still what russh wants, and drop the
      pin comment if not
- [ ] `cargo update`, then `cargo audit` — expect libcrux and crypto-bigint to
      resolve as transitive consequences
- [ ] `cargo build --release`, run the proxy tests, then exercise a real SSH
      session end to end: shell, SFTP, port forwarding and X11, since those are
      the paths russh changed between 0.55 and 0.60
- [ ] Bump `thiserror` to 2.x while in here
- [ ] Drop `**/Cargo.lock` from `.gitignore` and commit
      `ssh-reverse-proxy/Cargo.lock` so Dependabot starts watching this crate

### 3. SPA majors — the real work
- [ ] Bump one major at a time, build and click through the SPA after each:
      vite + @vitejs/plugin-vue, then vuetify, then pinia, then vue-router,
      then vue-tsc; echarts 6.0 → 6.1 is a patch and can ride along
- [ ] `npm run build` and `npm run typecheck` after each
- [ ] `./ctrl.sh recreate frontend-proxy` and check registration, restore-key
      and the scoreboard still render
- [ ] Re-run `npm audit` and record what is left

Vuetify 3 → 4 and pinia 2 → 4 are the ones likely to need code changes; budget
for that rather than expecting a clean bump.

### 4. Triage what cannot be fixed
- [ ] For each remaining alert with no published fix, dismiss it on GitHub with
      an explicit reason (build-time only / dev-server only / not reachable in
      the deployed configuration)
- [ ] Give `@vue/server-renderer` XSS and the echarts XSS a real read before
      dismissing either

### 5. Stop this from recurring
- [ ] Add `.github/dependabot.yml` covering all five ecosystems (`uv` for the
      three Python components, `npm` for the SPA, `cargo` for the proxy,
      `github-actions` for CI, `docker` for the base images) so updates arrive
      as PRs instead of accumulating
- [ ] Bump base images and CI actions in a separate change

## Pre-existing problems found while testing

None of these come from the dependency work — no Python source in `webapp/` or
`tests/` was touched by it.

- **The test web client was calling routes that no longer exist.**
  `register_student` posted to `/student/getkey` and `restore_student_key` to
  `/student/restoreKey`, both removed when student-facing views moved to the SPA
  in commit `31179f1`. Both helpers returned `False` on the resulting 404 rather
  than raising, so the failure surfaced as a bare "registration should succeed"
  assertion with nothing pointing at the cause, and cascaded into every e2e test
  that needs a student. Fixed to use `POST /api/v2/registration` and
  `POST /api/v2/restore-key`.
- **`test_join_and_cap` had two bugs, one hiding the other.** It gave every
  student in its loop the same placeholder public key, which the unique index on
  the key hash rejected on the second insert. With that fixed, its teardown
  failed instead: it asked `if not g.users` to decide which groups were empty
  before the user deletions had been flushed, so the relationship still reported
  its old members, those groups survived, and deleting the `GroupNameList` they
  reference hit `fk_user_group_source_list_id`. Now it flushes first and deletes
  the groups the list produced before the list.
- **`WEB_CONTAINER_NAME` can go unset and fail much later.** `create_app` sets
  it from `DockerClient.container_name_by_hostname("web")` inside a
  `try`/`except Exception` that logs, calls `failsafe()` and carries on, while
  `ref/core/instance.py` reads `current_app.config["WEB_CONTAINER_NAME"]`
  unconditionally. When many REF stacks start at once and the Docker daemon is
  saturated, the lookup can fail and the `KeyError` only appears later, during
  instance start. This is the concrete mechanism behind one of the remaining
  flakes.
- **`ref/services_api/ssh.py` logging does not reach the captured container
  logs.** Its `log.info`/`log.warning` calls are absent while its `print`-style
  `[API]` lines come through, so a rejection in `process_instance_request` can be
  seen happening without seeing which branch caused it. That is the main obstacle
  to diagnosing the parallel flakiness.

## Open questions

- Can the Dependabot page be read from here at all, or will this always be a
  local reconstruction? A PAT with `security_events` scope, or `gh auth login`,
  would make the real list available and let step 4 be done precisely.
- Are the SPA majors worth doing now, given that the remaining advisories are
  largely not reachable in production? Steps 1 and 2 are clearly worth it; step
  3 is a judgement call about keeping current versus the churn.

## Current status

**Done.** Every component relocked and audit-clean, all five images build, the
full suite is green apart from known pre-existing flakiness, and `ruff`, `ruff
format` and `mypy` all pass. Committed as `34cc64d` and `887e671` on `dev` and
pushed; `ref-utils` went out separately as `27c1fbd`.

### Test suite

| run | result |
|---|---|
| before the test fixes | 49 failed, 290 passed, 3 skipped, 11 errors |
| after | **3 failed, 347 passed, 3 skipped** |

The three stragglers are pre-existing flakiness under `-n 10`, not regressions.
Each of their files passes on its own: `test_rust_ssh_proxy.py` 24/24,
`test_grading_workflow.py` 17 passed + 1 skipped, `test_user_isolation.py`
10/10, `test_submission_workflow.py` 5/5. The set also moves between runs — one
of the three had passed in the previous run — which is what flakiness looks
like.

**The russh 0.65 rewrite is verified**, by suites other than the one named after
it: `test_ssh_key_types.py` passes 9/9 with real RSA, Ed25519 and ECDSA
connections plus SFTP file operations, `test_exercise_lifecycle.py` 20/20, and
`test_ssh_welcome_banner.py` 3/3. All of that traffic goes through the rewritten
accept/reject path.

**Blocked:** nothing.

## What changed, by component

### Python

`webapp/pyproject.toml` went from 40 entries to 34, but the 34 are a different
set: 18 packages that nothing imports were dropped, and 9 that the code *does*
import but never declared were added — `flask`, `flask-sqlalchemy`,
`sqlalchemy`, `werkzeug`, `alembic`, `itsdangerous`, `pygments`,
`python-dateutil`, `charset-normalizer`. Those worked only because some other
dependency happened to pull them in.

Dropped as unused: `argh`, `async-timeout`, `backports.tarfile`, `cffi`,
`coloredlogs`, `gunicorn`, `hypothesis`, `importlib-metadata`,
`jaraco.collections`, `pip-chill`, `platformdirs`, `py`, `pyparsing`, `rq`,
`toml`, `tomli`, `wcwidth`, `websocket-client`. Two of those are worth naming:
`gunicorn` was declared but unused (uWSGI is the server, via `run-server.sh`),
and `rq` was a job-queue dependency with no `import rq` anywhere.

Kept despite not being imported, with a comment at each site saying why:
`python-levenshtein` (fuzzywuzzy's C speedup backend), `uwsgi` (invoked as a
binary), `lxml` (the parser beautifulsoup4 is asked for by name), and the pytest
plugins (loaded by pytest, not imported).

`requires-python` went from `>=3.10` to `>=3.12` in all four. 3.10 was fiction:
the webapp image is Python 3.13 and the exercise base image is Ubuntu 24.04,
which is 3.12. The old floor also broke resolution outright, because the current
versions of several dependencies require 3.11+.

`ref-docker-base` was unpinned but **nothing was removed** — see the open
question about it.

### Rust

russh 0.55 -> 0.65 moved these:

- `check_server_key` takes `&PublicKeyOrCertificate` instead of `&PublicKey`.
- `auth_publickey` takes `VerifiedPublicKey<'_>` by value; the key is now at
  `.public_key`.
- `channel_open_session`, `channel_open_direct_tcpip` and
  `server_channel_open_forwarded_tcpip` each gained a `reply: ChannelOpenHandle`
  parameter and now return `Result<()>` instead of `Result<bool>`. **This is the
  change to review most closely**: accept/reject moved from the return value to
  a method call on `reply`, so every `Ok(false)` had to become an explicit
  `reply.reject(...)`. Dropping the handle rejects with
  `AdministrativelyProhibited`, which the error paths now rely on.
- Channel writes take `impl Into<bytes::Bytes>` rather than `CryptoVec`, so
  `bytes` is now a direct dependency and every `CryptoVec::from_slice` became
  `Bytes::copy_from_slice`.

Also `rand::thread_rng()` -> `rand::rng()`, and `new_from_slice` moved from the
`Mac` trait to `KeyInit` in hmac 0.13.

The remaining advisory is RUSTSEC-2023-0071, the RSA Marvin timing attack, which
has no fix in the 0.9/0.10 line. It is **not reachable here**: Marvin is about
RSA private-key operations, and the proxy holds no RSA private key — the host
key is generated as Ed25519 and both container keys on disk are `ssh-ed25519`.
Verifying a student's RSA public key is a public-key operation. Safe to dismiss
with that reason.

### SPA

vite 6 -> 8 (which switches the bundler to rolldown), vuetify 3 -> 4,
pinia 2 -> 4, vue-router 4 -> 5, `@vitejs/plugin-vue` 5 -> 6, vue-tsc 2 -> 3.

One source change was needed. In Vuetify 4 the `selection` slot of `v-select`
hands over the entry from `:items` directly, where Vuetify 3 handed over its own
wrapper — so `item.raw.title` in `src/pages/Register.vue` became `item.title`.
The old wrapper is still available as a separate `internalItem` slot prop.

An incidental fix: the old `package-lock.json` was generated inside the Alpine
build container and contained only the musl rollup binary, so `npm ci` could not
install it on a glibc host at all. The regenerated lockfile carries every
platform binding, so it installs both in the container and on a developer
machine.

### Base images and CI

All within the existing major, so no data-directory or path migrations:
`python:3.13.1-bookworm` -> `3.13.18-bookworm` (same 3.13, so the hardcoded
`/usr/local/lib/python3.13/site-packages` path still resolves),
`caddy:2.8-alpine` -> `2.11.9-alpine`, `postgres:17.2` -> `17.9` (same major, so
the existing data directory is readable). CI actions moved to their current
majors.

`docker-compose.yml` is generated once by `prepare.py` and is not refreshed by
`ctrl.sh build`, so the postgres bump needed `./prepare.py` (without `--fresh`,
which would have rotated every secret).

### Linting: CI was already red, for an unrelated reason

`ruff check .` reports several hundred findings on code that nobody touched —
no Python source file changed in this work. The cause is that CI installed the
linters unpinned (`uv tool install ruff`) and **ruff 0.16 turned on rule
families that used to be opt-in**. Measured across versions on this unmodified
tree:

| ruff | `check` findings | `format --check` dirty files |
|---|---|---|
| 0.15.10 | 0 (all checks passed) | 0 |
| 0.16.0 | 758 | 3 |
| 0.17.4 | 741 | 3 |

So the codebase is clean under the rules it was written against, and went red the
moment ruff 0.16 shipped. `RUFF_VERSION` and `MYPY_VERSION` are now pinned in
`.github/workflows/ci.yml`, with the pre-commit hook and `.claude/CLAUDE.md`
updated to install the same versions.

That restores a meaningful signal; it does not decide whether to adopt ruff's new
defaults. Doing so is a real piece of work — roughly 480 of the findings are
auto-fixable, the rest are judgement calls like `BLE001` (blind `except
Exception`) and `S110` (`try`/`except`/`pass`) — and it should be its own change,
not smuggled in with a dependency bump.

mypy is unaffected: clean on 49 source files at both 1.20.1 and 2.4.1.

### The images had to start reading the lockfiles

Switching from `==` to floors exposed a gap: **neither image ever read a
`uv.lock`.** `webapp/Dockerfile` and `ref-docker-base/Dockerfile` both did

    COPY pyproject.toml /tmp/
    RUN uv pip install --system --break-system-packages .

which resolves the manifest at build time. With `==` pins that happened to be
exact, so the images were reproducible by accident. With floors it would have
meant "install whatever is newest on PyPI today", and two builds of the same
commit could differ — the committed lockfiles would have pinned nothing that
ships.

Both now export the lock and install that instead:

    COPY pyproject.toml uv.lock /tmp/
    RUN uv export --frozen --no-dev --no-emit-project --no-hashes -o requirements.txt \
        && uv pip install --system --break-system-packages -r requirements.txt

`--frozen` is the useful part beyond pinning: the build fails if `uv.lock` and
`pyproject.toml` have drifted, instead of quietly relocking. That gives 53 pinned
packages for the webapp and 90 for the exercise base image, direct and
transitive.

### Second pass: the non-security updates

With the advisories cleared, the remaining items were staleness rather than
risk, and were done as a second pass.

- **`ref-utils` updated in its own repository.** Relocked, floors raised to the
  locked versions, `requires-python` to 3.12. Its own suite passes (220 tests),
  ruff is clean under its explicit `select = ["E", "F", "W", "I"]`, pyright
  reports no errors, and pip-audit finds nothing. Committed as `27c1fbd` on
  `dev` and pushed; the submodule pointer in this repo moves with it.
- **`ace-builds` v1.20.0 -> v1.45.2.** Checked every file the admin file browser
  actually names before bumping: `src-noconflict/ace.js`, `theme-chrome`, and
  the modes `plain_text`, `assembly_x86`, `c_cpp`, `python`, `sh`, `yaml` and
  `makefile`. All present at the new tag.
- **SSH proxy moved to Debian trixie** (`rust:1.99-trixie` +
  `debian:trixie-slim`). The two stages must name the same Debian release,
  because the binary is copied between them. The Rust version is now pinned
  instead of floating on `rust:bookworm`; 1.99 is what the russh work was built
  against, and russh 0.65 declares an MSRV of 1.89.
- **`cargo build --release --locked`**, which is the Cargo equivalent of the
  `uv export --frozen` change: the build fails if `Cargo.lock` disagrees with
  `Cargo.toml` rather than resolving something new.
- **Node 22 -> 24 (LTS)** for the SPA build stages, verified by running
  `npm ci` and `npm run build` (which includes `vue-tsc --noEmit`) inside
  `node:24-alpine`.
- **Webapp base to `python:3.13.18-trixie`.** The 3.13 part has to stay, because
  the `sitecustomize.py` COPY target hardcodes
  `/usr/local/lib/python3.13/site-packages`.
- **`multiarch/qemu-user-static` left alone.** It is unpinned, but upstream
  publishes no version tags at all, only architecture-pair names, so there is
  nothing to pin to short of a digest.

### A latent bug the trixie bump surfaced

`webapp/Dockerfile` installed `docker` *and* `docker.io`. In Debian those are
unrelated: `docker.io` is the Docker engine and CLI, while `docker` is a
system-tray applet for docklet applications. Trixie dropped the applet, so the
build failed with `Package 'docker' has no installation candidate`. Installing
it was never intentional; the fix is to install only `docker.io`, which is what
provides `/usr/bin/docker`.

## Can an existing REF installation break?

- **The database is safe.** postgres stays on major 17, and no model or migration
  changed, so no schema work is implied.
- **Exercise images must be rebuilt.** `ref-docker-base` dependencies moved, so
  every exercise image built from it is stale until rebuilt. Existing *running*
  instances keep their old image and are unaffected until they are recreated.
- **The student toolbox changed under them.** ipython 8 -> 9, opencv 4 -> 5,
  mypy 1 -> 2, oauthlib 3 -> 4 and zipp 3 -> 4 are all majors inside the
  exercise container. An exercise that pins behaviour from the old versions can
  break, and this repo has no exercises checked in to test against.
- **The SSH proxy is the real risk.** The russh accept/reject rewrite is on the
  path every student connection takes. Unit tests do not cover it; the e2e SSH
  tests do.
- **`requires-python >=3.12`** means REF no longer claims to support 3.10/3.11.
  Nothing in the project ran on those, but a developer on an older host will now
  get a resolution error rather than a silent mismatch.

## Pre-existing problems found while testing

None of these come from the dependency work — no Python source in `webapp/` or
`tests/` was touched by it.

- **The test web client was calling routes that no longer exist.**
  `register_student` posted to `/student/getkey` and `restore_student_key` to
  `/student/restoreKey`, both removed when student-facing views moved to the SPA
  in commit `31179f1`. Both helpers returned `False` on the resulting 404 rather
  than raising, so the failure surfaced as a bare "registration should succeed"
  assertion with nothing pointing at the cause, and cascaded into every e2e test
  that needs a student. Fixed to use `POST /api/v2/registration` and
  `POST /api/v2/restore-key`.
- **`test_join_and_cap` had two bugs, one hiding the other.** It gave every
  student in its loop the same placeholder public key, which the unique index on
  the key hash rejected on the second insert. With that fixed, its teardown
  failed instead: it asked `if not g.users` to decide which groups were empty
  before the user deletions had been flushed, so the relationship still reported
  its old members, those groups survived, and deleting the `GroupNameList` they
  reference hit `fk_user_group_source_list_id`. Now it flushes first and deletes
  the groups the list produced before the list.
- **`WEB_CONTAINER_NAME` can go unset and fail much later.** `create_app` sets
  it from `DockerClient.container_name_by_hostname("web")` inside a
  `try`/`except Exception` that logs, calls `failsafe()` and carries on, while
  `ref/core/instance.py` reads `current_app.config["WEB_CONTAINER_NAME"]`
  unconditionally. When many REF stacks start at once and the Docker daemon is
  saturated, the lookup can fail and the `KeyError` only appears later, during
  instance start. This is the concrete mechanism behind one of the remaining
  flakes.
- **`ref/services_api/ssh.py` logging does not reach the captured container
  logs.** Its `log.info`/`log.warning` calls are absent while its `print`-style
  `[API]` lines come through, so a rejection in `process_instance_request` can be
  seen happening without seeing which branch caused it. That is the main obstacle
  to diagnosing the parallel flakiness.

## Open questions

- **`ref-docker-base` carries 10 dependencies that look like leftovers from an
  old `pip freeze`:** `backcall` and `pickleshare` (removed from IPython years
  ago), `pathlib2` and `importlib-resources` and `tomli` (Python-2-era or now
  stdlib), and `blinker`, `distro`, `lazy-object-proxy`, `wrapt`, `zipp`
  (transitive packages pinned as if direct). I unpinned but did not remove them,
  because `exercises/` is empty in this checkout and I cannot see whether a real
  exercise imports any of them. Removing all 10 is very likely correct and would
  shrink the image; it needs someone who can look at the live exercises.
- **`webapp/ref/view/visualization.py` is dead code and does not import.** It
  does `from gviz_api import DataTable`, and `gviz-api` is in no manifest and no
  lockfile, so the module would raise ImportError. Nothing imports it —
  `ref/view/__init__.py` does not list it — which is why this never surfaced.
  Either delete the file or wire it up and declare `gviz-api`; I did not add a
  dependency for code that nothing loads.
- **`ace-builds` is a git submodule pinned at v1.20.0** while upstream is on
  1.4x. Checked against OSV: **no advisories affect 1.20.0**, so this is
  staleness and not a security item. Being a submodule, Dependabot does not scan
  it either way. Bump it when someone can click through the admin editor.
- **`ref-docker-base/ref-utils` is a separate repository and was left alone.**
  Relocking it there did clear advisories in its own `uv.lock`, but that lock is
  not used to build anything: the exercise image installs it with
  `uv pip install -e .`, which resolves fresh and ignores the lock. Rather than
  strand a commit in a submodule that cannot be pushed from here, the change was
  reverted. Updating `ref-utils` is a task in its own repository.
- **Debian base of the SSH proxy is still bookworm** (`rust:bookworm` +
  `debian:bookworm-slim`) while trixie is current stable. Deliberately left
  alone: moving the build and runtime stages to a new glibc at the same time as
  the russh rewrite would confuse two sources of breakage.

## Decision log

- 2026-11-06 17:26 — Reconstructed the alert list with `pip-audit` / `npm audit`
  / `cargo audit` instead of reading the Dependabot page, because the page needs
  an authenticated session that is not available on this machine.
- 2026-11-06 17:26 — Chose to commit `Cargo.lock` rather than leave the proxy
  unscanned. A binary crate wants its lockfile committed anyway, and the proxy is
  the component exposed to student traffic.
- 2026-11-06 17:40 — **Stopped pinning direct dependencies with `==`.** For an
  application the lockfile is what makes a build reproducible; `==` in
  `pyproject.toml` duplicates that job and then blocks it, which is exactly how
  `pyjwt==2.12.1` and `pylint==4.0.5` sat on known advisories that a plain
  `uv lock --upgrade` could not move. Manifests now carry direct dependencies
  with `>=` floors set to the version the change was tested against, and
  `uv.lock` pins the exact tree. Raising a floor is then a deliberate act that
  says "we need at least this", and security updates arrive by relocking.
- 2026-11-06 17:45 — Declared the nine packages the webapp imports but never
  listed. Relying on a transitive dependency to supply `flask` or `sqlalchemy`
  works until an intermediate package drops it, and then it fails at import time
  in production rather than at resolution time.
- 2026-11-06 17:50 — Did not remove anything from `ref-docker-base`, only
  unpinned. The list is effectively a published interface for exercise authors,
  and with no exercises in this checkout there is no way to tell a leftover from
  something a submission imports. Logged as an open question instead of guessed.
- 2026-11-06 17:55 — Took russh to 0.65 rather than the 0.60.3 the advisory
  names. The API break is in the same places either way, so stopping at 0.60.3
  would buy a second migration later for nothing.
- 2026-11-06 18:00 — Did not run `cargo fmt`. CI has no Rust steps and the crate
  was already unformatted, so reformatting would have buried the russh changes
  in several hundred lines of whitespace.
- 2026-11-06 18:55 — Fast-forwarded `dev` to `main` before committing there.
  `origin/dev` was 13 commits behind `origin/main` with nothing of its own, and
  one of those commits had edited `ssh-reverse-proxy/src/api.rs` and
  `src/server.rs` — the two files the russh rewrite touches. Committing onto
  `dev` as it stood would have produced a tree without that work. The
  fast-forward is lossless precisely because `dev` had no unique commits.
- 2026-11-06 18:50 — Pinned the Rust version in the proxy image. `rust:bookworm`
  floated on latest stable, which is the same shape of problem as the unpinned
  ruff: an upstream release can change the build with no change here.
- 2026-11-06 18:25 — Made both images install from `uv.lock` via `uv export
  --frozen`. This is the half of the pinning change that was missing: floors in
  the manifest are only safe if something else pins exactly, and the images were
  not reading the lock at all. Without this, moving off `==` would have traded a
  reproducible build for a convenient manifest.
- 2026-11-06 18:20 — Raised the declared floors to the versions that are now
  locked, so a floor means "this is what we tested against" rather than
  "whatever the old pin happened to be". The jumps worth knowing about are
  `sqlalchemy` 2.0.49 -> 2.1.8 and `python-dateutil` 2.9.0 -> 4.0.0.
- 2026-11-06 18:15 — Checked `python-dateutil` 4.0 before accepting it. It drops
  Python < 3.11 and `six`, and makes `isoparse` reject sloppy numeric fields.
  Both call sites only do `from dateutil import tz`, which none of that touches.
- 2026-11-06 18:10 — Reverted the `ref-utils` submodule rather than commit into
  it from here.
- 2026-11-06 18:00 — Regenerated the SPA lockfile inside `node:22-alpine`, the
  image the Dockerfile builds in, so the lock matches the build environment
  rather than this host.
