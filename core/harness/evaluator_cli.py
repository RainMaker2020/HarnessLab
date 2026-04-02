#!/usr/bin/env python3
"""Run the configured evaluator (default: PlaywrightVisualEvaluator when strategy is playwright)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Repo root = parent of core/
_CORE = Path(__file__).resolve().parent.parent
_REPO = _CORE.parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from harness.env_bootstrap import load_harness_env
from harness.eval.evaluator import PlaywrightVisualEvaluator, build_evaluator
from harness.exceptions import HarnessError
from harness.git.git_paths import git_changed_paths_relative_to_workspace
from harness.config.harness_config import HarnessConfig


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

    edited = git_changed_paths_relative_to_workspace(cfg.workspace_dir)
    result = evaluator.run(edited_paths=edited)

    prefix = f"[{args.task_id}] " if args.task_id else ""
    print(f"{prefix}{result.output}")
    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
