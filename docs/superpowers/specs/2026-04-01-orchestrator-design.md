---
name: HarnessLab Orchestrator Design
description: Architecture spec for the Python orchestrator managing the AI-driven coding task lifecycle
type: project
---

# HarnessLab Orchestrator — Design Spec

**Date:** 2026-04-01
**Status:** Approved

---

## Overview

HarnessLab is an autonomous software engineering harness. It moves from ad-hoc prompting to systems architecture by managing the full lifecycle of AI-driven coding tasks: prompt generation, execution, evaluation, commit-or-rollback, and retry with injected error context.

---

## Directory Structure

```
HarnessLab/
├── harness.yaml              # Single source of truth for all paths & config
├── ARCHITECTURE.md           # Human-maintained rules (injected into every prompt)
├── SPEC.md                   # Human-maintained spec (injected into every prompt)
├── requirements.txt          # Python deps (pyyaml, rich)
├── .gitignore                # Ignores workspace/
├── core/
│   ├── main.py               # Orchestrator — entry point, task loop, circuit breaker
│   ├── prompt_generator.py   # PromptGenerator — assembles .harness_prompt.md
│   └── evaluator.py          # Evaluator — run_evaluator() placeholder, Playwright later
├── sandbox/
│   └── Dockerfile            # Claude CLI + Playwright environment
├── docs/
│   └── history.json          # Failure log (control plane — version controlled)
└── workspace/                # GITIGNORED — Data plane, own git repo
    ├── PLAN.md               # [ ] task list (human writes this)
    └── .harness_prompt.md    # Generated fresh per attempt (never committed)
```

---

## Control Plane vs. Data Plane

| | Control Plane | Data Plane |
|---|---|---|
| **Location** | `HarnessLab/` root | `workspace/` |
| **Git** | Version-controlled (harness repo) | Own git repo (`workspace/.git`) |
| **Owned by** | Human | Claude Code (jailed here) |
| **Contents** | `harness.yaml`, `ARCHITECTURE.md`, `SPEC.md`, `core/`, `docs/history.json` | `PLAN.md`, generated code, `.harness_prompt.md` |

---

## `harness.yaml` Schema

```yaml
workspace_dir: ./workspace
architecture_doc: ./ARCHITECTURE.md
spec_doc: ./SPEC.md
plan_file: ./workspace/PLAN.md
history_file: ./docs/history.json
build_command: "echo 'EVALUATOR_PLACEHOLDER: always passes'"
max_retries: 3
claude_model: claude-sonnet-4-6
worker_mode: local  # future: docker
```

---

## Task Lifecycle (per task, per attempt)

```
1. BASELINE   — record current git HEAD in workspace/
2. GENERATE   — PromptGenerator writes workspace/.harness_prompt.md
                 (rules + task + last failure if retry)
3. EXECUTE    — claude --print "$(cat .harness_prompt.md)" --cwd ./workspace
4. EVALUATE   — run_evaluator() runs build_command from harness.yaml
5a. SUCCESS   — Exit 0 AND evaluator passes →
                 git add . && git commit -m "feat: TASK_XX completed"
                 PromptGenerator appends summary to workspace/CHANGELOG.md
5b. FAILURE   — Exit non-zero OR evaluator fails →
                 git reset --hard && git clean -fd
                 append to docs/history.json
                 increment retry counter
                 if retries >= max_retries: HALT (human intervention)
                 else: go to step 2 with error context injected
5c. SOS       — Exit code 2 → pause immediately, NO rollback
                 print critical message and wait for human
```

---

## Task ID Format

PLAN.md tasks use `- [ ] TASK_01: description` format. Task IDs (TASK_01, TASK_02, etc.) are deterministic keys in `docs/history.json` and git commit messages.

---

## Module Boundaries

| Module | Responsibility | Depends on |
|---|---|---|
| `core/main.py` | Task loop, retry counter, circuit breaker, git ops, SOS handler | `prompt_generator`, `evaluator`, `harness.yaml` |
| `core/prompt_generator.py` | Read ARCHITECTURE.md + SPEC.md + task + last history entry → write `.harness_prompt.md` + CHANGELOG.md on success | `harness.yaml` paths |
| `core/evaluator.py` | Run `build_command`, return pass/fail + stdout/stderr | `harness.yaml` |

---

## `docs/history.json` Schema

```json
[
  {
    "task_id": "TASK_01",
    "attempt": 1,
    "timestamp": "2026-04-01T12:00:00Z",
    "claude_exit_code": 1,
    "evaluator_passed": false,
    "evaluator_output": "...",
    "claude_stdout": "...",
    "claude_stderr": "..."
  }
]
```

Only the most recent failure for the current task is injected into the retry prompt.

---

## Worker Modes

`harness.yaml` `worker_mode` controls execution strategy:

- `local` — `subprocess.run(["claude", ...])` directly on host
- `docker` (future) — `subprocess.run(["docker", "exec", container_id, "claude", ...])` using sandbox/Dockerfile

`core/main.py` Worker class routes to the correct backend based on this setting.

---

## Special Exit Codes

| Exit Code | Meaning | Action |
|---|---|---|
| `0` | Success | Proceed to evaluator |
| `1` | Failure | Rollback + retry |
| `2` | SOS — Human intervention requested | Pause, no rollback, halt loop |

---

## Constraints

- `workspace/` is in `.gitignore` of the harness repo but is its own independent git repo for rollbacks.
- `.harness_prompt.md` is never committed (added to `workspace/.gitignore`).
- `CHANGELOG.md` in `workspace/` is written by `PromptGenerator` on every success and committed with the task.
- Circuit breaker: 3 consecutive failures on the same task → HALT.
