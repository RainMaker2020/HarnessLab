---
description: Run full autonomous plan until complete or blocked
allowed-tools: Read, Write, Edit, MultiEdit, Bash, Glob, Grep
---

Autonomous loop. Do not stop until PLAN.md has no unchecked tasks.

For each iteration:
1. /harness-next — implement next task
2. /harness-eval — evaluate result  
3. If HARNESS_EVAL: APPROVE → continue
4. If HARNESS_EVAL: REJECT:
   - Read failure details
   - Fix and retry (max 3 times total for this task)
   - If still failing after 3: write workspace/.harness_blocked.md, stop

Constraints — never skip:
- Never mark done without passing build
- Never retry more than 3 times  
- Always update PROGRESS.md on success