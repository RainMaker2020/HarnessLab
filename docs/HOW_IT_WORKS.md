# How HarnessLab works (repository guide)

This document describes how the **HarnessLab** codebase is structured, how **Phase 2** runs the task loop via **Claude Code** (`CLAUDE.md`, slash commands, hooks), and which components still use the **Claude CLI** versus the **Anthropic HTTP API**.

---

## 1. Entry points (Phase 2)

| Invocation | What runs |
|------------|-----------|
| **Claude Code** + `/harness-run` | Primary autonomous loop: read `PLAN.md`, implement tasks, eval hooks (see root `CLAUDE.md`). |
| `python manage.py --init "…"` | **Scaffolder**: writes `ARCHITECTURE.md`, `SPEC.md`, and `PLAN.md` (paths from `harness.yaml`), then exits. |
| `python manage.py --distill` | Appends prompt + git diff to `paths.distillation_export` (JSONL). |
| `python core/evaluator_cli.py` | Runs the configured evaluator (build, Playwright, vision, etc.) from `harness.yaml`. |
| **`MasterOrchestrator`** (`orchestration.mode: recursive`) | Provisions each EPIC module directory (git isolation, `harness.yaml`, contracts), then runs **`claude -p "Execute the PLAN.md in this module."`** with `cwd` set to that module (requires Claude Code CLI on `PATH`). |

For day-to-day work, prefer **Claude Code** at the repo root with `/harness-run`; use **`MasterOrchestrator`** when you want Python-driven EPIC iteration from `harness.yaml`.

---

## 2. Configuration: single source of truth

**`harness.yaml`** (repo root) is parsed into **`HarnessConfig`** (`core/harness_config.py`).

Important sections:

| Section | Purpose |
|---------|---------|
| **`paths.*`** | Where `ARCHITECTURE.md`, `SPEC.md`, `workspace/`, history, trajectories, Chroma, EPIC interfaces, etc. live. Defaults keep everything under **`./project/`** (see `harness.yaml`). |
| **`models.*`** | Model id per **role** (`planner`, `generator`, `evaluator`, `contract_verifier`). Used by `ModelRouter` for CLI `--model` and by API calls where applicable. |
| **`runtime.*`** | `mode: local` runs workers on the host; `docker` runs `claude` inside the sandbox image (`core/sandbox.py`). |
| **`evaluation.*`** | Evaluator strategy (`exit_code`, `playwright`, …), `build_command`, optional `contract_test_command`, timeouts, vision rubric. |
| **`orchestration.*`** | Linear vs recursive, retries, `test_first`, `interactive_mode`, distillation, wisdom RAG, etc. |

**`ModelRouter`** (`core/model_router.py`) turns `config.models[role]` into CLI fragments like `["--model", "<id>"]` for subprocesses. It does not call HTTP APIs by itself.

---

## 3. Two ways the harness talks to “Claude”

| Mechanism | Used where | Credentials |
|-----------|------------|-------------|
| **Claude CLI** (`claude` on `PATH`) | Scaffolder, contract file generation, **Worker** task execution | Whatever the CLI uses (Claude Code login / subscription). **Not** read from `ANTHROPIC_API_KEY` automatically. |
| **Anthropic Python SDK** (`anthropic.Anthropic()`) | Vision evaluation, **contract verification** (NEGOTIATE gate) | **`ANTHROPIC_API_KEY`** in the environment (or explicit client config). |

So: **scaffolding and implementation runs can work with CLI-only auth**, while **contract negotiation and vision paths need an API key** unless you change the code.

---

## 4. Task flow (Phase 2 — agentic loop)

The **PLAN** loop is executed by the **generator agent** in Claude Code, guided by `CLAUDE.md` and `/harness-next`. In-repo building blocks still apply:

1. **`PlanParser`** (`core/harness_plan.py`) — same checklist semantics for tests and tools; agents edit `PLAN.md` directly.

2. **Contracts (optional `test_first`)** — **`ContractPlanner`** / **`ContractVerifier`** in `core/planner.py` and `core/evaluator.py` unchanged for CLI-driven contract generation when you run those tools.

3. **`PromptGenerator`** — still assembles prompts if you invoke it from scripts.

4. **`build_evaluator(config)`** (`core/evaluator.py`) — factory for **`ExitCodeEvaluator`**, **`PlaywrightVisualEvaluator`**, **`PlaywrightFunctionalEvaluator`**; used by **`evaluator_cli.py`** and **`MasterOrchestrator`** test wiring.

5. **Hooks** — `core/hooks/post_write_gate.py` runs `evaluation.build_command` after workspace writes; `core/hooks/pre_stop_check.sh` blocks session end while `PLAN.md` has unchecked tasks.

6. **Wisdom RAG** (`core/wisdom_rag.py`) — optional Chroma enrichment when integrated into your workflow.

---

## 5. Module map (what each major file does)

| Module | Responsibility |
|--------|----------------|
| `manage.py` | CLI: `--init` (scaffolder), `--distill` (trajectory JSONL). |
| `core/harness_config.py` | Parse `harness.yaml` → `HarnessConfig`. |
| `core/model_router.py` | Resolve model strings per role; CLI `--model` args. |
| `core/scaffolder.py` | `--init`: `claude --print` → parse markers → write ARCHITECTURE / SPEC / PLAN. |
| `core/planner.py` | Generate `*.contract.test.ts` via `claude --print` (planner model). |
| `core/harness_plan.py` | `PlanParser`, `HistoryManager` for PLAN / history (no Python loop). |
| `core/master_orchestrator.py` | EPIC provisioning; inner loop removed in Phase 2 (see README). |
| `core/evaluator.py` | Exit-code builds, Playwright + vision (API), **ContractVerifier** (API). |
| `core/prompt_generator.py` | Assemble per-task prompt files and workspace changelog context. |
| `core/git_isolation.py` | Git helpers used by master flow (see imports there). |
| `core/project_mapper.py` | Map tasks to impacted files / situational context for prompts. |
| `core/sandbox.py` | Docker lifecycle and `docker exec … claude`. |
| `core/trajectory_logger.py` | Append run records for `distillation_export`. |
| `core/ui.py` | Console UX, Observation Deck. |
| `core/wisdom_rag.py` | Chroma-based retrieval when `wisdom_rag` is on. |
| `core/exceptions.py` | `HarnessError` and related. |

---

## 6. Control plane vs data plane (on disk)

Default layout (`harness.yaml`) keeps the **framework** at the repo root (`core/`, `harness.yaml`, `tests/`, `docs/HOW_IT_WORKS.md`, …) and the **harnessed app + harness state** under **`project/`**:

| Location | Role |
|----------|------|
| Repo root: `harness.yaml` | **Orchestrator config** — edit paths here if you want a different prefix than `./project/`. |
| `project/ARCHITECTURE.md`, `project/SPEC.md` | **Control plane** for the app — rules and product spec. |
| `project/workspace/` | **Data plane** — generated app, git history of AI work, `PLAN.md`, prompt buffers, screenshots. Ignored via `.gitignore` (you may commit parts of it if you choose). |
| `project/docs/history.json` | Append-only style log of attempts and outcomes. |
| `project/docs/trajectories.jsonl` | Optional golden trajectories when distillation is enabled. |
| `project/docs/wisdom_chroma/` | Optional Chroma persistence for Wisdom RAG. |
| `project/docs/EPIC.md`, `project/docs/interfaces.json` | Recursive mode contracts between modules. |

The repo’s **`docs/`** folder holds **repository documentation** (e.g. this file); `docs/EPIC.md` is a short pointer to `project/docs/EPIC.md`.

---

## 7. Tests

`tests/` mirrors core behavior: config parsing, scaffolder CLI invocation, orchestrator loop, evaluators, planners, etc. Run from repo root:

```bash
./.venv/bin/python -m pytest
```

---

## 8. Related reading

- **`README.md`** — overview, setup, Observation Deck, economics.  
- **`project/docs/EPIC.md`** — recursive orchestration inputs (when using master orchestrator).  
- Internal design notes under **`docs/superpowers/`** — historical specs and plans (not required to run the harness).
