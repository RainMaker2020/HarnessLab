---
description: Identify and implement the next task in PLAN.md
allowed-tools: Read, Write, Edit, MultiEdit, Bash, Glob, Grep
---

Execute **one** task using this sequence:

1. Read `harness.yaml` → note `paths.plan_file`, `paths.workspace_dir`, and `evaluation.build_command`.
2. Read `workspace/PROGRESS.md` (under the configured workspace dir if different) — orient yourself.
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
13. Report: `TASK_XX complete.`
