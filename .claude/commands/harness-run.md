---
description: Autonomous loop until PLAN is complete or blocked
allowed-tools: Read, Write, Edit, MultiEdit, Bash, Glob, Grep
---

Autonomous loop. Do not stop until `PLAN.md` (see `harness.yaml` → `paths.plan_file`) has **no** unchecked tasks, or you are blocked.

**Each iteration:**

1. Invoke **/harness-next** — implement exactly the next pending task.
2. Invoke **/harness-eval** — run `python3 core/evaluator_cli.py` (or `./.venv/bin/python core/evaluator_cli.py`) and honor the exit code.
3. If evaluation output / exit code indicates failure: read errors, fix, retry (max **3** attempts per task).
4. After 3 failed attempts for the same task: write `workspace/.harness_blocked.md` with context and stop.

**Constraints:**

- Never mark a task `[x]` without a passing build (`evaluation.build_command`).
- Never skip updating `PROGRESS.md` after a successful task.
- Respect **Stop** hook: you cannot exit cleanly while unchecked tasks remain in `PLAN.md`.
