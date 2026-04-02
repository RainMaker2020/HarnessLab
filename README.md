# HarnessLab

**The industrial-grade autonomous software factory**

HarnessLab is a post–prompt-engineering framework for long-running, autonomous software development. It is inspired by Anthropic’s engineering note *Harness design for long-running application development* and shifts emphasis from ad hoc chat toward **systemic orchestration**.

By separating a **control plane** (your rules, config, and history) from a **data plane** (the AI’s git-isolated workspace), HarnessLab aims for a resilient environment where agents do not only emit code—they **negotiate contracts**, satisfy evaluators, and can be gated by **visual quality** checks.

---

## Core idea: harness over prompting

Many agent failures trace to context overload, unchecked optimism, and drifting requirements. This project addresses that through:

| Concept | What it means here |
|--------|---------------------|
| **Air-gap** | Control-plane files for the app under `project/` (`ARCHITECTURE.md`, `SPEC.md`, …) stay distinct from the mutable `project/workspace/`; repo root holds the harness (`core/`, `harness.yaml`). |
| **Adversarial evaluation** | Evaluators can run build steps, **Playwright** screenshots, and **vision** rubrics (see `core/evaluator.py` and `harness.yaml`). |
| **Recursive state** | Git in `project/workspace/` with **auto-rollback** on failed attempts; optional human **Observation Deck** for commit / rollback / override. |

---

## System architecture (AIRE-oriented)

| Capability | Description | Notes |
|------------|-------------|--------|
| **Contract negotiation** | Test-first flow: generated contract tests are verified against `SPEC.md` before implementation (`test_first`, `contract_negotiation_max_retries`). | Implemented (`core/planner.py`, `core/evaluator.py`). |
| **The “Eye”** | Playwright capture + optional multimodal (vision) review of the running UI. | Set `evaluation.strategy: playwright` in `harness.yaml`. Default config often uses `exit_code` for quick iteration. |
| **Situational awareness** | Recursive **EPIC** mode uses `project/docs/interfaces.json` (configurable) as the authoritative public contract map between modules. | Requires `orchestration.mode: recursive` and `paths.interfaces_file`. |
| **Efficiency engine** | Asymmetric model routing (`models.planner`, `generator`, `evaluator`, `contract_verifier` in `harness.yaml`). | Implemented (`core/model_router.py`). |
| **The Jail** | Docker image with Claude Code, Node, Playwright; configurable memory and network. | Set `runtime.mode: docker` to run workers in the sandbox; default is `local`. |
| **Economic bridge** | Trajectory logging to `project/docs/trajectories.jsonl`; optional **Wisdom RAG** (ChromaDB under `project/docs/wisdom_chroma`). | Toggle `orchestration.distillation_mode` / `wisdom_rag`. |

---

## Repository layout

```text
HarnessLab/
├── core/                 # Orchestrator (config, git, workers, evaluators, UI)
├── project/              # App bundle: ARCHITECTURE/SPEC, workspace/, harness docs (see project/README.md)
├── docs/                 # Repo docs (e.g. HOW_IT_WORKS); EPIC stub points at project/docs/
├── sandbox/              # Docker image for isolated execution
├── tests/                # Pytest suite
├── harness.yaml          # Single source of truth for paths and behavior (default: paths under ./project/)
├── manage.py             # CLI: `--init` (scaffolder), `--distill` (trajectory append)
└── CLAUDE.md             # Worker laws + hooks (Phase 2 agentic loop)
```

**How it fits together (modules, task loop, CLI vs API auth):** see [`docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md).

---

## Getting started

### Prerequisites

- **Python** 3.10+ (project development targets 3.11+ in internal plans)
- **Git**
- **Docker** (optional but recommended for sandboxed workers and the provided image)
- **Claude Code CLI**: `npm install -g @anthropic-ai/claude-code`
- **API keys for the Brain** (vision + contract verifier): copy [`.env.example`](.env.example) to `.env` in the repo root and fill in the keys you need (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `OPENAI_COMPATIBLE_API_KEY`, …), or export them in the shell. **Which model each role uses** is set in [`harness.yaml`](harness.yaml) under `models:`. Optional per-role model overrides: `HARNESS_MODEL_EVALUATOR`, `HARNESS_MODEL_CONTRACT_VERIFIER`, etc. (see `HarnessConfig.effective_models`). The harness loads `.env` on startup when you run `manage.py`, `core/evaluator_cli.py`, or other entry points that call `env_bootstrap`.
- For **Playwright** visual evaluation: after `pip install`, run `playwright install chromium` on the host (the sandbox Dockerfile installs Chromium for container runs)

### Setup

```bash
git clone https://github.com/YOUR_USER/HarnessLab.git
cd HarnessLab
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Claude Code and the Harness MCP

[Claude Code](https://github.com/anthropics/claude-code) (terminal agent) and HarnessLab are complementary: Claude Code drives edits and commands; the harness supplies `PLAN.md`, evaluators, and MCP tools. You **do not** need a separate project—open this repository in Claude Code and follow root `CLAUDE.md`.

**Project MCP config** lives at `.mcp.json` in the repo root (the usual convention for editor and CLI MCP clients). Claude Code loads **project-scoped** servers from that file so the team shares one definition. Official reference: [Connect Claude Code to tools via MCP](https://code.claude.com/docs/en/mcp).

Checked-in server (stdio — run from **repository root** so `.venv/bin/python` and `core/mcp_server.py` resolve):

```json
{
  "mcpServers": {
    "harnesslab": {
      "command": ".venv/bin/python",
      "args": ["core/mcp_server.py"]
    }
  }
}
```

Tools exposed include `harness_next_task`, `harness_eval`, `harness_commit`, and `harness_progress` (see `CLAUDE.md`). Prefer these over ad hoc shell for harness workflows when the server is connected.

**Register via CLI** (optional; creates or updates `.mcp.json` with project scope):

```bash
cd /path/to/HarnessLab
claude mcp add --transport stdio --scope project harnesslab -- .venv/bin/python core/mcp_server.py
```

On first use, Claude Code may prompt you to **approve** project MCP servers. To reset those choices: `claude mcp reset-project-choices`.

**Path quirks:** If stdio fails to resolve the interpreter, point `command` at an absolute path to `.venv/bin/python`, or use environment variable expansion in `.mcp.json` (Claude Code supports `${VAR}` / `${VAR:-default}` in `command` and `args` — see the MCP doc above). **WSL:** use your Linux checkout path (for example `~/Projects/HarnessLab`); the same JSON and CLI apply as on native Linux.

### Build the sandbox image (optional)

Build from the **repository root** (the Dockerfile copies `requirements.txt`, `core/`, etc.):

```bash
docker build -f sandbox/Dockerfile -t harnesslab-sandbox:latest .
```

(`docker build ./sandbox` fails: the context must be `.` so those paths exist.)

Point `harness.yaml` → `runtime.image` at this tag and set `runtime.mode: docker` when you want workers inside the container.

### Constitutional documents

Keep these aligned with what you inject into prompts:

| File | Role |
|------|------|
| `project/ARCHITECTURE.md` | Non-negotiable engineering rules |
| `project/SPEC.md` | Product definition and constraints |
| `project/workspace/PLAN.md` | Linear task checklist (`TASK_01`, …) |

For **recursive / EPIC** orchestration, edit `project/docs/EPIC.md` and `project/docs/interfaces.json` (see `core/master_orchestrator.py`). Paths are configurable under `harness.yaml` → `paths`.

If you previously used `ARCHITECTURE.md` / `SPEC.md` / `workspace/` at the **repository root**, move those into `project/` to match the defaults (or point `paths` back at the old locations).

### Agentic-native workflow (Phase 2)

1. **Scaffold** (once per greenfield project):

   ```bash
   python manage.py --init "your product idea" -y
   ```

2. **Run the task loop** in **Claude Code** at the repo root: follow root `CLAUDE.md`, connect the **Harness MCP** ([Claude Code and the Harness MCP](#claude-code-and-the-harness-mcp)), then use `/harness-run` (or `/harness-next` per task). Hooks under `core/hooks/` run the build after workspace writes and block **Stop** while `PLAN.md` has unchecked tasks.

3. **Optional CLIs** from the repo root:

   ```bash
   python manage.py --distill --task TASK_01   # append trajectory JSONL (needs paths.distillation_export)
   python core/evaluator_cli.py                # run evaluator from harness.yaml
   ```

**Hooks and Python:** `.claude/settings.json` runs `.venv/bin/python core/hooks/post_write_gate.py` so PostToolUse uses the project virtualenv. If `.venv` does not exist yet, use `python3 core/hooks/post_write_gate.py` or create the venv first (`python -m venv .venv`).

**Recursive / EPIC:** with `orchestration.mode: recursive`, `core/master_orchestrator.py` provisions each module workspace, then runs **`claude -p "Execute the PLAN.md in this module."`** in that directory (Claude Code CLI on `PATH`). The `scripts/ablation_study.py` tool temporarily patches `harness.yaml` per scenario and runs the same Claude invocation in the configured workspace to time ablation runs.

---

## Observation Deck

After evaluation, the harness can pause for a human decision **only if** `orchestration.interactive_mode: true` in `harness.yaml` (default is `false` for unattended runs).

When enabled, the menu matches the implementation in `core/ui.py`:

- **`(c) commit`** — Approve and merge the sprint to git history.
- **`(r) rollback`** — Discard the attempt and retry (subject to retry limits).
- **`(o) override`** — Edit `project/workspace/` by hand, then resume evaluation.

---

## Economics: trajectories and distillation

Successful runs can append structured records to `project/docs/trajectories.jsonl` (path configurable in `harness.yaml`). That log is intended as a **golden dataset** for later distillation or fine-tuning of smaller models—paired with `orchestration.distillation_mode` and **Wisdom RAG** indexing when you enable them.

---

## CI/CD

| Workflow | When | What |
|----------|------|------|
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | Push / PR to `main` or `master` | `pip install -r requirements.txt` and `pytest tests/` on Python **3.11** and **3.12** |
| [`.github/workflows/docker-publish.yml`](.github/workflows/docker-publish.yml) | Push a tag `v*` (e.g. `v1.0.0`), or **Run workflow** in the Actions tab | Build [`sandbox/Dockerfile`](sandbox/Dockerfile) and push to **GitHub Container Registry** (`ghcr.io/<owner>/<repo>/harnesslab-sandbox` with semver / `sha` / `latest` tags) |

For the sandbox image, set `harness.yaml` → `runtime.image` to the published tag if you run workers in Docker. New packages may default to private; adjust visibility under the repository’s **Packages** settings if others need to pull the image.

---

## License

MIT — intended for the AI Reliability Engineering (AIRE) community. Add a `LICENSE` file in the repo root when you publish.

---

## Name note

The CLI banners and `harness.yaml` header use the product name **HarnessingLab**; this repository is **HarnessLab**. They refer to the same system.
