#!/usr/bin/env python3
"""Run the configured evaluator (default: PlaywrightVisualEvaluator when strategy is playwright)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Repo root = parent of core/
_CORE = Path(__file__).resolve().parent
_REPO = _CORE.parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from env_bootstrap import load_harness_env
from evaluator import PlaywrightVisualEvaluator, build_evaluator
from exceptions import HarnessError
from harness_config import HarnessConfig


def _git_changed_files(workspace: Path) -> list[str] | None:
    """Return paths changed vs HEAD, or None if not a git repo."""
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Playwright visual evaluation (or strategy from harness.yaml)."
    )
    parser.add_argument(
        "task_id",
        nargs="?",
        metavar="TASK_XX",
        help="Optional task id for logging context (printed on success/failure).",
    )
    parser.add_argument(
        "--config",
        default="harness.yaml",
        type=Path,
        help="Path to harness.yaml (default: ./harness.yaml).",
    )
    parser.add_argument(
        "--playwright-visual",
        action="store_true",
        help="Force PlaywrightVisualEvaluator regardless of evaluation.strategy.",
    )
    args = parser.parse_args()

    load_harness_env()
    config_path = args.config
    if not config_path.is_absolute():
        config_path = (_REPO / config_path).resolve()
    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        sys.exit(2)

    try:
        cfg = HarnessConfig.from_yaml(config_path)
    except HarnessError as exc:
        print(exc, file=sys.stderr)
        sys.exit(2)

    if args.playwright_visual:
        evaluator = PlaywrightVisualEvaluator(cfg)
    else:
        evaluator = build_evaluator(cfg)

    edited = _git_changed_files(cfg.workspace_dir)
    result = evaluator.run(edited_paths=edited)

    prefix = f"[{args.task_id}] " if args.task_id else ""
    print(f"{prefix}{result.output}")
    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
