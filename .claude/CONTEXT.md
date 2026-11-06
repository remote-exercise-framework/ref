# CONTEXT

## Ongoing

_Nothing in flight._

## Recent changes

- Updated every dependency across webapp, tests, ref-docker-base, ref-utils, the SPA and the Rust proxy; images now install from the lockfiles, and the SSH proxy moved to russh 0.65. See `plans/done/2026-11-06_17-26_dependency-security-update.md`.
- Added web request timeout and unified user-facing failure messages.
- Set `sshd_config` mode to 0644 when copied into the exercise base image.
- Fixed the ssh-reverse-proxy log filter and migrated startup logs to tracing.
- Documented backup excludes for overlayfs-derived directories.
