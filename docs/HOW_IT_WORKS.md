# How HarnessLab works (repository guide)

This document describes how the **HarnessLab** codebase is structured, how **Phase 2** runs the task loop via **Claude Code** (`CLAUDE.md`, slash commands, hooks), and which components use the **Claude CLI** (worker) versus **HTTP APIs** (Brain: evaluator / contract verifier).

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

**`harness.yaml`** (repo root) is parsed into **`HarnessConfig`** (`core/harness/config/harness_config.py`).

Important sections:

| Section | Purpose |
|---------|---------|
| **`paths.*`** | Where `ARCHITECTURE.md`, `SPEC.md`, `workspace/`, history, trajectories, Chroma, EPIC interfaces, etc. live. Defaults keep everything under **`./project/`** (see `harness.yaml`). |
| **`models.*`** | Model id per **role** (`planner`, `generator`, `evaluator`, `contract_verifier`). Used by `ModelRouter` for CLI `--model` and by API calls where applicable. |
| **`runtime.*`** | `mode: local` runs workers on the host; `docker` runs `claude` inside the sandbox image (`core/harness/runtime/sandbox.py`). |
| **`evaluation.*`** | Evaluator strategy (`exit_code`, `playwright`, …), `build_command`, optional `contract_test_command`, timeouts, vision rubric. |
| **`orchestration.*`** | Linear vs recursive, retries, `test_first`, `interactive_mode`, distillation, wisdom RAG, etc. |

**`ModelRouter`** (`core/harness/config/model_router.py`) turns `config.models[role]` into CLI fragments like `["--model", "<id>"]` for subprocesses. It does not call HTTP APIs by itself.

---

## 3. Worker (CLI) vs Brain (HTTP API)

### Roles in code

- **Worker (Claude CLI only)** — Anything that runs `claude` as a subprocess: interactive **Claude Code** sessions, **`manage.py --init`** (scaffolder), **contract test generation** (`ContractPlanner`), and **EPIC** module runs (`claude -p …`). These use `models.planner` (scaffold + contract file generation) or ad hoc `claude` invocations. They are **not** routed through OpenAI/DeepSeek; auth is whatever the **Claude Code** CLI uses (subscription / login). That is **separate** from `.env` Brain keys unless you change the code.
- **Brain (HTTP only)** — Only **`evaluator`** and **`contract_verifier`** (`core/harness/llm/llm_provider.py`, `brain_client_for_role`). Used for **Playwright + vision** rubric scoring and **contract verification** (NEGOTIATE gate). Supports **Anthropic**, **OpenAI**, or **OpenAI-compatible** servers (e.g. DeepSeek via `base_url`).

So **`planner`-driven Python paths** (`--init`, generating `TASK_XX.contract.test.ts`) are **still the Claude CLI**, not the Brain APIs. The Brain only runs when the harness calls the evaluator or contract verifier.

### Default vs OpenAI / DeepSeek Brain

If you omit `evaluator_provider` / `contract_verifier_provider` in `harness.yaml`, the code **defaults the Brain to Anthropic** (`ANTHROPIC_API_KEY`). To use **OpenAI** or **DeepSeek** as Brain, you must set those keys explicitly, for example:

- `evaluator_provider: openai` or `openai-compatible`
- `evaluator_base_url` / `contract_verifier_base_url` when using compatible APIs (e.g. DeepSeek)
- Matching `.env` entries: see `.env.example`

Vision evaluation requires a **model that supports images** on whatever provider you choose.

| Mechanism | Used where | Credentials |
|-----------|------------|-------------|
| **Claude CLI** (`claude` on `PATH`) | Scaffolder (`--init`), **contract file generation** (`models.planner`), EPIC `claude -p`, **PLAN** implementation in Claude Code | Claude Code CLI login / subscription. **Not** read from `ANTHROPIC_API_KEY` automatically. |
| **Brain APIs** (Anthropic, OpenAI, or OpenAI-compatible) | Vision evaluation, **contract verification** (NEGOTIATE gate) | Per role: **`ANTHROPIC_API_KEY`**, **`OPENAI_API_KEY`**, **`DEEPSEEK_API_KEY`**, or **`OPENAI_COMPATIBLE_API_KEY`** as resolved in `llm_provider.py`. |

**Summary:** Implementation and planner-side tooling can rely on **Claude CLI only**. **Vision and contract-verify gates** need the **Brain** keys and `harness.yaml` provider settings. If both Brain roles use OpenAI or DeepSeek, the **worker** remains **Claude Code / `claude` CLI** for coding and planning subprocesses.

---

## 4. Task flow (Phase 2 — agentic loop)

The **PLAN** loop is executed by the **generator agent** in Claude Code, guided by `CLAUDE.md` and `/harness-next`. In-repo building blocks still apply:

1. **`PlanParser`** (`core/harness/planning/harness_plan.py`) — same checklist semantics for tests and tools; agents edit `PLAN.md` directly.

2. **Contracts (optional `test_first`)** — **`ContractPlanner`** (`core/harness/planning/planner.py`) generates tests via **`claude --print`**; **`ContractVerifier`** (`core/harness/eval/evaluator.py`) gates them via the **Brain** API.

3. **`PromptGenerator`** (`core/harness/prompts/prompt_generator.py`) — assembles prompts if you invoke it from scripts.

4. **`build_evaluator(config)`** (`core/harness/eval/evaluator.py`) — factory for **`ExitCodeEvaluator`**, **`PlaywrightVisualEvaluator`**, **`PlaywrightFunctionalEvaluator`**; used by **`core/harness/evaluator_cli.py`** and orchestration.

5. **Hooks** — `core/hooks/post_write_gate.py` runs `evaluation.build_command` after workspace writes; `core/hooks/pre_stop_check.sh` blocks session end while `PLAN.md` has unchecked tasks.

6. **Wisdom RAG** (`core/harness/prompts/wisdom_rag.py`) — optional Chroma enrichment when integrated into your workflow.

---

## 5. Module map (what each major file does)

Shims under `core/*.py` re-export the `harness` package where noted in imports. Implementation lives under **`core/harness/`**.

| Module | Responsibility |
|--------|----------------|
| `manage.py` | CLI: `--init` (scaffolder), `--distill` (trajectory JSONL). |
| `core/harness/config/harness_config.py` | Parse `harness.yaml` → `HarnessConfig`. |
| `core/harness/config/model_router.py` | Resolve model strings per role; CLI `--model` args; Brain roles `evaluator` / `contract_verifier`. |
| `core/harness/planning/scaffolder.py` | `--init`: `claude --print` → parse markers → write ARCHITECTURE / SPEC / PLAN. |
| `core/harness/planning/planner.py` | Generate `*.contract.test.ts` via `claude --print` (**planner** model — CLI, not Brain). |
| `core/harness/planning/harness_plan.py` | `PlanParser`, `HistoryManager` for PLAN / history (no Python loop). |
| `core/harness/planning/master_orchestrator.py` | EPIC provisioning and `claude -p` per module. |
| `core/harness/eval/evaluator.py` | Exit-code builds, Playwright + vision (Brain API), **ContractVerifier** (Brain API). |
| `core/harness/llm/llm_provider.py` | Brain clients: Anthropic, OpenAI, OpenAI-compatible. |
| `core/harness/mcp_server.py` | MCP stdio server: PLAN, eval, gated commit. |
| `core/harness/prompts/prompt_generator.py` | Assemble per-task prompt files and workspace changelog context. |
| `core/harness/git/git_isolation.py` | Git helpers for EPIC / isolation. |
| `core/harness/prompts/project_mapper.py` | Map tasks to impacted files / situational context for prompts. |
| `core/harness/runtime/sandbox.py` | Docker lifecycle and `docker exec … claude`. |
| `core/harness/runtime/trajectory_logger.py` | Append run records for `distillation_export`. |
| `core/harness/runtime/ui.py` | Console UX, Observation Deck. |
| `core/harness/prompts/wisdom_rag.py` | Chroma-based retrieval when `wisdom_rag` is on. |
| `core/harness/exceptions.py` | `HarnessError` and related. |

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
