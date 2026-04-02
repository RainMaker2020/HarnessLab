---
description: Autonomous loop until PLAN is complete or blocked
allowed-tools: Read, Write, Edit, MultiEdit, Bash, Glob, Grep
---

Autonomous loop. Do not stop until `PLAN.md` (see `harness.yaml` → `paths.plan_file`) has **no** unchecked tasks, or you are blocked.

**Each iteration:**

### 1 — Implement the next task

1. Read `harness.yaml` → note `paths.plan_file`, `paths.workspace_dir`, and `evaluation.build_command`.
2. Read `PROGRESS.md` (under the configured workspace dir) — orient yourself.
3. Read `ARCHITECTURE.md` and `SPEC.md` (paths from `harness.yaml`).
4. Find the next unchecked task: `grep -n '^\- \[ \]' <plan_file> | head -1` (substitute the real plan path).
5. If none: print `PLAN COMPLETE` and stop.
6. If `test_first` / contract flow applies: check for `$TASK_ID.contract.test.ts` under the workspace dir and read it.
7. List existing files: `find <workspace_dir> -type f` (exclude `.git` as needed).
8. Implement the task incrementally.
9. Run the build command from `harness.yaml` in `paths.workspace_dir`.
10. If the build fails: fix and repeat until exit code 0.
11. Update `PROGRESS.md` with completion notes.
12. Change `- [ ] TASK_XX` to `- [x] TASK_XX` in `PLAN.md` only after the build passes.

### 2 — Evaluate

Run the evaluator CLI from the repo root (use the project venv if present):

```
./.venv/bin/python core/evaluator_cli.py [TASK_XX]
```

Or: `python3 core/evaluator_cli.py [TASK_XX]`

- Exit code 0 → evaluation passed. Non-zero → read the output, fix issues, rebuild, re-run.
- Add `--playwright-visual` to force `PlaywrightVisualEvaluator` even if `harness.yaml` uses another strategy.

If MCP (`harnesslab`) is connected, use **`harness_eval`** and **`harness_commit`** tools instead of the CLI.

### 3 — Retry / block

- If evaluation fails: read the printed output, fix the issue, re-run the build, re-evaluate. Max **3** attempts per task.
- After 3 failed attempts: write `workspace/.harness_blocked.md` with full context and stop.

**Constraints:**
- Never mark a task `[x]` without a passing build (`evaluation.build_command`).
- Never skip updating `PROGRESS.md` after a successful task.
- Respect the **Stop** hook: you cannot exit cleanly while unchecked tasks remain in `PLAN.md`.
