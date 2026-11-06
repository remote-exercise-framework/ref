# CONTEXT

## Ongoing

- [Dependency security update](plans/ongoing/2026-11-06_17-26_dependency-security-update.md) — WIP, 2026-11-06 17:26. Clearing Dependabot alerts: Python refresh first, then commit the Rust lockfile, then SPA majors.

## Recent changes

- Added web request timeout and unified user-facing failure messages.
- Set `sshd_config` mode to 0644 when copied into the exercise base image.
- Fixed the ssh-reverse-proxy log filter and migrated startup logs to tracing.
- Documented backup excludes for overlayfs-derived directories.
