# How HarnessLab works (repository guide)

This document describes how the **HarnessLab** codebase is structured, how execution flows from `python core/main.py`, and which components talk to the **Claude CLI** versus the **Anthropic HTTP API**.

---

## 1. Entry point

| Invocation | What runs |
|------------|-----------|
| `python core/main.py` | Loads `harness.yaml` from the repo root, then either **linear** or **recursive** orchestration (see below). |
| `python core/main.py --init "…"` | **Scaffolder only**: writes `project/ARCHITECTURE.md`, `project/SPEC.md`, and `project/workspace/PLAN.md` (default paths) from your idea, then exits. Does not run the task loop. |

Implementation: `core/main.py`.

- **`orchestration.mode: linear`** (default): builds a `SubOrchestrator` and runs the PLAN task loop.
- **`orchestration.mode: recursive`**: imports `MasterOrchestrator` from `core/master_orchestrator.py` for EPIC-style multi-module orchestration (see that file and `project/docs/EPIC.md`).

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

## 4. Linear run: end-to-end task flow (`SubOrchestrator`)

`core/sub_orchestrator.py` owns the main loop for **`orchestration.mode: linear`**.

1. **`GitManager.ensure_repo()`**  
   Ensures `workspace/` is a git repo (initialized if needed).

2. **`PlanParser.next_task()`**  
   Reads `workspace/PLAN.md`, finds the first unchecked line matching  
   `- [ ] TASK_XX: description`.

3. **Per task** (conceptually):

   - **If `test_first` is true — NEGOTIATE**  
     - **`ContractPlanner`** (`core/planner.py`): runs **`claude --print …`** with the **planner** model; writes `workspace/{TASK_ID}.contract.test.ts`.  
     - **`ContractVerifier`** (`core/evaluator.py`): calls **`anthropic` Messages API** with **`contract_verifier`** (or **`evaluator`**) model; checks the contract against `SPEC.md`.  
     - On success, the contract file is **committed** (“locked”) before implementation.

   - **`PromptGenerator`** (`core/prompt_generator.py`): builds the prompt file (from `ARCHITECTURE.md`, `SPEC.md`, task context, optional Wisdom RAG snippets, prior failures from `docs/history.json`, etc.).

   - **`Worker.run()`**  
     Runs **`claude --print <prompt> --model <generator model>`** with **`cwd=workspace/`** (local) or **`DockerManager.exec_claude`** (docker). This is the **implementation** step.

   - **`build_evaluator(config)`** (`core/sub_orchestrator.py`): returns an evaluator chain based on `evaluation.strategy` — e.g. **`ExitCodeEvaluator`** (runs `build_command`), optionally **`PlaywrightVisualEvaluator`** + Anthropic vision, optional contract test command merged with primary result.

   - **Git / history**  
     On success: commit, **`PlanParser.mark_done`**, append **`HistoryManager`**, optional **`TrajectoryLogger`**.  
     On failure: optional **rollback** (`auto_rollback`), retries up to **`max_retries_per_task`**.

4. **Optional `ObservationDeck`** (`core/ui.py`): if **`interactive_mode`** is true, human can commit / rollback / override after evaluation.

5. **Wisdom RAG** (`core/wisdom_rag.py`): when enabled, indexes or queries Chroma under `paths.wisdom_store` to enrich prompts.

---

## 5. Module map (what each major file does)

| Module | Responsibility |
|--------|----------------|
| `core/main.py` | CLI (`--init`), load config, dispatch linear vs recursive. |
| `core/harness_config.py` | Parse `harness.yaml` → `HarnessConfig`. |
| `core/model_router.py` | Resolve model strings per role; CLI `--model` args. |
| `core/scaffolder.py` | `--init`: `claude --print` → parse markers → write ARCHITECTURE / SPEC / PLAN. |
| `core/planner.py` | Generate `*.contract.test.ts` via `claude --print` (planner model). |
| `core/sub_orchestrator.py` | PLAN loop, negotiate → prompt → worker → evaluate, git, history. |
| `core/master_orchestrator.py` | Recursive / EPIC orchestration across sub-workspaces. |
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
