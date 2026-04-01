# Harness project bundle

By default, **`harness.yaml`** points all harness paths here:

- **`ARCHITECTURE.md`**, **`SPEC.md`** — control-plane specs for the app you are building
- **`workspace/`** — git-isolated workspace, `PLAN.md`, generated code (see `.gitignore` at repo root)
- **`docs/`** — per-run history, optional trajectories, Wisdom RAG store, EPIC / interfaces for recursive mode

To use another directory, change the `paths:` section in `harness.yaml` (paths are relative to the file that contains them).
