# Phase S1 — Launcher Pipe Root-Cause Audit

## Audit Findings

- **Attempt 1 Failure**: Spawning `main.py` with `stdout=subprocess.PIPE` and `stderr=subprocess.PIPE` without an active reading thread caused OS pipe buffer saturation (Windows 4KB-64KB OS limit).
- **Classification**: `LAUNCHER_UNCONSUMED_PIPE_BUFFER`.
- **Selected Output Strategy**: **Option A (Append-Only File Sinks)**.
  - `stdout` -> `canonical_runner_stdout.log` (mode `a`, `buffering=1`)
  - `stderr` -> `canonical_runner_stderr.log` (mode `a`, `buffering=1`)
  - `stdin` -> `subprocess.DEVNULL`
