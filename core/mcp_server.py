#!/usr/bin/env python3
"""HarnessLab MCP server (stdio): PLAN, eval, gated commit, PROGRESS — JSON-RPC via MCP."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Repo layout: core/ is on sys.path for harness modules (same pattern as evaluator_cli).
_CORE = Path(__file__).resolve().parent
_REPO = _CORE.parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from env_bootstrap import load_harness_env
from evaluator import EvalResult, PlaywrightVisualEvaluator
from exceptions import HarnessError
from harness_config import HarnessConfig
from harness_plan import PlanParser

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "The 'mcp' package is required. Install with: pip install mcp"
    ) from exc


def _default_config_path() -> Path:
    return (_REPO / "harness.yaml").resolve()


def _git_changed_files(workspace: Path) -> list[str] | None:
    """Paths changed vs HEAD under workspace, or None if not a git work tree."""
    if not (workspace / ".git").exists():
        return None
    r = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=workspace,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    names = [line.strip() for line in r.stdout.splitlines() if line.strip()]
    r2 = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=workspace,
        capture_output=True,
        text=True,
    )
    if r2.returncode == 0:
        names.extend(line.strip() for line in r2.stdout.splitlines() if line.strip())
    return sorted({n.replace("\\", "/") for n in names})


def _load_config(config_path: Path | None = None) -> HarnessConfig:
    path = config_path or _default_config_path()
    if not path.exists():
        raise HarnessError(f"Config not found: {path}")
    return HarnessConfig.from_yaml(path)


def _progress_path(cfg: HarnessConfig) -> Path:
    """PROGRESS.md lives next to PLAN.md (harness workspace)."""
    return cfg.plan_file.parent / "PROGRESS.md"


def _format_verdict(result: EvalResult, task_id: str | None) -> str:
    """Human-readable tool output with explicit APPROVE/REJECT line."""
    verdict = "APPROVE" if result.passed else "REJECT"
    prefix = f"[{task_id}] " if task_id else ""
    return (
        f"{prefix}VERDICT: {verdict}\n"
        f"exit_code={result.exit_code}\n"
        f"---\n"
        f"{result.output.strip()}"
    )


def run_playwright_eval(cfg: HarnessConfig) -> EvalResult:
    """Run Playwright visual evaluator (ignores evaluation.strategy exit_code shortcut)."""
    edited = _git_changed_files(cfg.workspace_dir)
    evaluator = PlaywrightVisualEvaluator(cfg)
    return evaluator.run(edited_paths=edited)


def harness_next_task_text(cfg: HarnessConfig) -> str:
    """Return the next unchecked PLAN line or a clear message if none."""
    plan = PlanParser(cfg.plan_file)
    t = plan.next_task()
    if t is None:
        return "No unchecked tasks (- [ ]) in PLAN.md."
    return f"{t.task_id}: {t.description}"


def harness_eval_text(cfg: HarnessConfig, task_id: str) -> str:
    """Run evaluator and return verdict block."""
    result = run_playwright_eval(cfg)
    return _format_verdict(result, task_id)


def harness_progress_text(cfg: HarnessConfig) -> str:
    """Return PROGRESS.md contents."""
    p = _progress_path(cfg)
    if not p.exists():
        return f"(PROGRESS.md not found at {p}; create it next to PLAN.md.)"
    return p.read_text()


def harness_commit_impl(cfg: HarnessConfig, task_id: str, message: str, repo_root: Path) -> str:
    """
    1) Require task_id to match the first unchecked PLAN task.
    2) Run Playwright visual evaluator; on failure, do not commit.
    3) git add -A && git commit at repo_root.
    """
    if not message or not message.strip():
        return "Error: commit message must be non-empty."

    plan = PlanParser(cfg.plan_file)
    next_t = plan.next_task()
    if next_t is None:
        return "Error: no pending task in PLAN.md; refusing commit."
    if next_t.task_id != task_id.strip():
        return (
            f"Error: task_id mismatch. Current next task is {next_t.task_id!r}; "
            f"got {task_id!r}. Fix PLAN or pass the correct task id."
        )

    result = run_playwright_eval(cfg)
    if not result.passed:
        return (
            "Commit blocked: evaluator did not pass.\n\n" + _format_verdict(result, task_id)
        )

    if not (repo_root / ".git").exists():
        return f"Error: not a git repository at {repo_root}."

    add = subprocess.run(
        ["git", "add", "-A"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if add.returncode != 0:
        return f"Error: git add failed: {(add.stderr or add.stdout).strip()}"

    commit = subprocess.run(
        ["git", "commit", "-m", message.strip()],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0:
        err = (commit.stderr or commit.stdout or "").strip()
        return f"Error: git commit failed: {err}"

    rev = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    sha = rev.stdout.strip() if rev.returncode == 0 else "unknown"
    return f"Committed {task_id} at {sha}\n{commit.stdout.strip()}"


mcp = FastMCP(
    "harnesslab",
    instructions=(
        "HarnessLab tools: read PLAN/progress, run visual eval, commit only after eval passes."
    ),
)


@mcp.tool()
def harness_next_task() -> str:
    """Return the next unchecked `- [ ] TASK_XX` line from PLAN.md (harness.yaml paths)."""
    load_harness_env()
    cfg = _load_config()
    return harness_next_task_text(cfg)


@mcp.tool()
def harness_eval(task_id: str) -> str:
    """Run the Playwright visual evaluator for the workspace; returns APPROVE/REJECT verdict and logs."""
    load_harness_env()
    cfg = _load_config()
    return harness_eval_text(cfg, task_id=task_id.strip())


@mcp.tool()
def harness_commit(task_id: str, message: str) -> str:
    """Commit only after visual eval passes; must match current next PLAN task. Uses git at repo root."""
    load_harness_env()
    cfg = _load_config()
    return harness_commit_impl(cfg, task_id, message, _REPO)


@mcp.tool()
def harness_progress() -> str:
    """Return workspace PROGRESS.md (beside PLAN.md)."""
    load_harness_env()
    cfg = _load_config()
    return harness_progress_text(cfg)


def main() -> None:
    load_harness_env()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
