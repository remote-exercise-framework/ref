# CONTEXT

## Ongoing

- **SPA + end-to-end test coverage** (WIP, 2026-11-23 12:40) — phase 1 is done:
  382 vitest tests in `spa-frontend/`, plus `tests/e2e/test_spa_forms.py` (32) and
  `tests/e2e/test_spa_scoreboard_flow.py` (27) driving the real bundle in Chromium.
  Phase 2 is the rest of the generated exercise catalogue, the grading e2e extensions
  and the `tests/api/` revival. See
  `plans/ongoing/2026-11-23_10-50_spa-and-e2e-tests.md`.

## Recent changes

- Moved the `/home/user/.user_environ` snapshot from root's `_task` into the unprivileged `task` wrapper, closing a symlink attack that gave students root in their instance; also restricted the sudoers rule to `(root)` and fixed the wrapper's RELRO linker flag. `task check` in a submission now runs tests with that snapshot (the student's environment) unless the grader passes `--caller-env`.
- Updated every dependency across webapp, tests, ref-docker-base, ref-utils, the SPA and the Rust proxy; images now install from the lockfiles, and the SSH proxy moved to russh 0.65. See `plans/done/2026-11-06_17-26_dependency-security-update.md`.
- Added web request timeout and unified user-facing failure messages.
- Set `sshd_config` mode to 0644 when copied into the exercise base image.
- Fixed the ssh-reverse-proxy log filter and migrated startup logs to tracing.
- Documented backup excludes for overlayfs-derived directories.
