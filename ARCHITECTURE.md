# HarnessLab Architecture Rules

> This file is injected into every Claude Code prompt. Edit it to enforce project-wide constraints.

## Rules

1. All code must be written inside the `workspace/` directory only.
2. Do not modify any files outside the current task scope.
3. Every function must have a docstring.
4. Follow PEP 8 for Python. Use 4-space indentation.
5. Do not install new packages without listing them in `requirements.txt`.

## Test-first mode (`orchestration.test_first`)

When enabled, the harness negotiates a `TASK_XX.contract.test.ts` file before code generation. The **build/evaluator gate** is still `evaluation.build_command`. To actually **execute** the locked contract tests after the worker implements the task, either include them in `build_command` (e.g. `npm test`) or set **`evaluation.contract_test_command`** with placeholders `{task_id}`, `{contract_rel}`, `{contract_path}`.
