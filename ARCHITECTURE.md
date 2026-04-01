# HarnessLab Architecture Rules

> This file is injected into every Claude Code prompt. Edit it to enforce project-wide constraints.

## Rules

1. All code must be written inside the `workspace/` directory only.
2. Do not modify any files outside the current task scope.
3. Every function must have a docstring.
4. Follow PEP 8 for Python. Use 4-space indentation.
5. Do not install new packages without listing them in `requirements.txt`.
