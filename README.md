# HarnessLab

**The industrial-grade autonomous software factory**

HarnessLab is a post–prompt-engineering framework for long-running, autonomous software development. It is inspired by Anthropic’s engineering note *Harness design for long-running application development* and shifts emphasis from ad hoc chat toward **systemic orchestration**.

By separating a **control plane** (your rules, config, and history) from a **data plane** (the AI’s git-isolated workspace), HarnessLab aims for a resilient environment where agents do not only emit code—they **negotiate contracts**, satisfy evaluators, and can be gated by **visual quality** checks.

---

## Core idea: harness over prompting

Many agent failures trace to context overload, unchecked optimism, and drifting requirements. This project addresses that through:

| Concept | What it means here |
|--------|---------------------|
| **Air-gap** | Control-plane files (`ARCHITECTURE.md`, `SPEC.md`, `harness.yaml`, `docs/`) stay distinct from the mutable `workspace/`. |
| **Adversarial evaluation** | Evaluators can run build steps, **Playwright** screenshots, and **vision** rubrics (see `core/evaluator.py` and `harness.yaml`). |
| **Recursive state** | Git in `workspace/` with **auto-rollback** on failed attempts; optional human **Observation Deck** for commit / rollback / override. |

---

## System architecture (AIRE-oriented)

| Capability | Description | Notes |
|------------|-------------|--------|
| **Contract negotiation** | Test-first flow: generated contract tests are verified against `SPEC.md` before implementation (`test_first`, `contract_negotiation_max_retries`). | Implemented (`core/planner.py`, `core/evaluator.py`, `sub_orchestrator`). |
| **The “Eye”** | Playwright capture + optional multimodal (vision) review of the running UI. | Set `evaluation.strategy: playwright` in `harness.yaml`. Default config often uses `exit_code` for quick iteration. |
| **Situational awareness** | Recursive **EPIC** mode uses `docs/interfaces.json` as the authoritative public contract map between modules. | Requires `orchestration.mode: recursive` and `paths.interfaces_file`. |
| **Efficiency engine** | Asymmetric model routing (`models.planner`, `generator`, `evaluator`, `contract_verifier` in `harness.yaml`). | Implemented (`core/model_router.py`). |
| **The Jail** | Docker image with Claude Code, Node, Playwright; configurable memory and network. | Set `runtime.mode: docker` to run workers in the sandbox; default is `local`. |
| **Economic bridge** | Trajectory logging to `docs/trajectories.jsonl`; optional **Wisdom RAG** (ChromaDB under `docs/wisdom_chroma`). | Toggle `orchestration.distillation_mode` / `wisdom_rag`. |

---

## Repository layout

```text
HarnessLab/
├── core/                 # Orchestrator (config, git, workers, evaluators, UI)
├── docs/                 # Control plane: history, trajectories, EPIC/interfaces (as used)
├── sandbox/              # Docker image for isolated execution
├── workspace/            # Data plane: git-isolated AI workspace (see .gitignore)
├── tests/                # Pytest suite
├── harness.yaml          # Single source of truth for paths and behavior
└── core/main.py          # Entry point
```

---

## Getting started

### Prerequisites

- **Python** 3.10+ (project development targets 3.11+ in internal plans)
- **Git**
- **Docker** (optional but recommended for sandboxed workers and the provided image)
- **Claude Code CLI**: `npm install -g @anthropic-ai/claude-code`
- **Anthropic API key**: `export ANTHROPIC_API_KEY=...` (used by contract verification and vision paths)
- For **Playwright** visual evaluation: after `pip install`, run `playwright install chromium` on the host (the sandbox Dockerfile installs Chromium for container runs)

### Setup

```bash
git clone https://github.com/YOUR_USER/HarnessLab.git
cd HarnessLab
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Build the sandbox image (optional)

```bash
docker build -t harnesslab-sandbox:latest ./sandbox
```

Point `harness.yaml` → `runtime.image` at this tag and set `runtime.mode: docker` when you want workers inside the container.

### Constitutional documents

Keep these aligned with what you inject into prompts:

| File | Role |
|------|------|
| `ARCHITECTURE.md` | Non-negotiable engineering rules |
| `SPEC.md` | Product definition and constraints |
| `workspace/PLAN.md` | Linear task checklist (`TASK_01`, …) |

For **recursive / EPIC** orchestration, you also need `docs/EPIC.md` and `docs/interfaces.json` (see `core/master_orchestrator.py`).

### Run the harness

From the repository root:

```bash
python core/main.py
```

`harness.yaml` selects **linear** vs **recursive** orchestration via `orchestration.mode`.

---

## Observation Deck

After evaluation, the harness can pause for a human decision **only if** `orchestration.interactive_mode: true` in `harness.yaml` (default is `false` for unattended runs).

When enabled, the menu matches the implementation in `core/ui.py`:

- **`(c) commit`** — Approve and merge the sprint to git history.
- **`(r) rollback`** — Discard the attempt and retry (subject to retry limits).
- **`(o) override`** — Edit `workspace/` by hand, then resume evaluation.

---

## Economics: trajectories and distillation

Successful runs can append structured records to `docs/trajectories.jsonl` (path configurable in `harness.yaml`). That log is intended as a **golden dataset** for later distillation or fine-tuning of smaller models—paired with `orchestration.distillation_mode` and **Wisdom RAG** indexing when you enable them.

---

## License

MIT — intended for the AI Reliability Engineering (AIRE) community. Add a `LICENSE` file in the repo root when you publish.

---

## Name note

The CLI banners and `harness.yaml` header use the product name **HarnessingLab**; this repository is **HarnessLab**. They refer to the same system.
