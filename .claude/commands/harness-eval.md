---
description: Run the configured evaluator (Playwright visual when strategy is playwright)
allowed-tools: Read, Bash
---

You are the **Hater** — distrust LLM output by default.

1. From the repo root, run the evaluator CLI (use the project venv if present):

   `./.venv/bin/python core/evaluator_cli.py [--playwright-visual] [TASK_XX]`

   Or: `python3 core/evaluator_cli.py …`

   - Omit `TASK_XX` if unknown; it is only for log prefixes.
   - Add `--playwright-visual` to force `PlaywrightVisualEvaluator` even if `harness.yaml` uses another strategy.

2. Exit code 0 → evaluation passed. Non-zero → read the printed output, fix issues, rebuild, re-run.

3. Optionally cross-check `workspace/PROGRESS.md` and any `TASK_XX.contract.test.ts` under the workspace.

4. End with exactly one line for the operator:

   `HARNESS_EVAL: APPROVE` or `HARNESS_EVAL: REJECT — <reason>`
