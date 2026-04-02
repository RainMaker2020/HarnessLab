---
description: Implement the next pending task from workspace/PLAN.md
allowed-tools: Read, Write, Edit, MultiEdit, Bash, Glob, Grep
---

Execute ONE task from workspace/PLAN.md using this exact sequence:

1. Read workspace/PROGRESS.md — orient yourself, know what's built
2. Read ARCHITECTURE.md and SPEC.md — know the constraints  
3. grep -n '^\- \[ \]' workspace/PLAN.md | head -1 — find next task
4. If none: print "PLAN COMPLETE" and stop
5. Check if workspace/$TASK_ID.contract.test.ts exists — read it if so
6. run: find workspace/ -type f | grep -v .git — know what exists
7. Implement the task. Build incrementally.
8. Run: $(grep build_command harness.yaml | cut -d'"' -f2)
9. If build fails: fix it. Repeat until passing.
10. Update workspace/PROGRESS.md with task completion note
11. Change - [ ] TASK_XX to - [x] TASK_XX in workspace/PLAN.md
12. Report: "TASK_XX complete."