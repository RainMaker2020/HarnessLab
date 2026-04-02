#!/usr/bin/env python3
"""HarnessLab management CLI — scaffolder (--init) and trajectory distillation (--distill)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
_CORE = _REPO_ROOT / "core"
sys.path.insert(0, str(_CORE))

from harness.env_bootstrap import load_harness_env
from harness.exceptions import HarnessError
from harness.config.harness_config import HarnessConfig
from harness.config.model_router import ModelRouter
from harness.planning.scaffolder import Scaffolder
from harness.runtime.trajectory_logger import TrajectoryLogger
from harness.runtime.ui import ObservationDeck


def _git_diff(workspace: Path) -> str:
    """Unified diff vs HEAD (tracked + unstaged changes)."""
    r = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=workspace,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return (r.stderr or r.stdout or "").strip()
    return (r.stdout or "").strip()


def cmd_init(prompt: str, *, force: bool, config_path: Path) -> None:
    load_harness_env()
    ui = ObservationDeck()
    if not config_path.exists():
        ui.fatal_error(f"harness.yaml not found at {config_path}")
        sys.exit(1)
    try:
        config = HarnessConfig.from_yaml(config_path)
        Scaffolder(config, ModelRouter(config)).run(prompt, force=force)
        ui.info(
            f"Scaffolder wrote {config.architecture_doc}, {config.spec_doc}, and {config.plan_file}."
        )
    except HarnessError as exc:
        ui.fatal_error(str(exc))
        sys.exit(1)


def cmd_distill(task_id: str | None, config_path: Path) -> None:
    """Append one trajectory record from current workspace git diff + prompt buffer."""
    load_harness_env()
    ui = ObservationDeck()
    if not config_path.exists():
        ui.fatal_error(f"harness.yaml not found at {config_path}")
        sys.exit(1)
    try:
        config = HarnessConfig.from_yaml(config_path)
    except HarnessError as exc:
        ui.fatal_error(str(exc))
        sys.exit(1)

    export = config.distillation_export
    if export is None:
        ui.fatal_error("paths.distillation_export must be set in harness.yaml for --distill.")
        sys.exit(1)

    tid = task_id or "MANUAL"
    prompt_text = ""
    buf = config.prompt_buffer_path
    if buf.exists():
        prompt_text = buf.read_text(encoding="utf-8", errors="replace")

    diff = _git_diff(config.workspace_dir)
    TrajectoryLogger(export).append(tid, prompt_text, diff)
    ui.info(f"Appended trajectory for {tid} → {export}")


def main() -> None:
    parser = argparse.ArgumentParser(description="HarnessLab — init workspace or log distillation.")
    parser.add_argument(
        "--config",
        type=Path,
        default=_REPO_ROOT / "harness.yaml",
        help="Path to harness.yaml",
    )
    parser.add_argument(
        "--init",
        metavar="PROMPT",
        default=None,
        help="Scaffold ARCHITECTURE.md, SPEC.md, and workspace PLAN.md from an idea",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="With --init, overwrite existing ARCHITECTURE.md / SPEC.md without confirmation",
    )
    parser.add_argument(
        "--distill",
        action="store_true",
        help="Append git diff + prompt buffer to paths.distillation_export (JSONL)",
    )
    parser.add_argument(
        "--task",
        metavar="TASK_XX",
        default=None,
        help="With --distill, label for the trajectory record (default: MANUAL)",
    )

    args = parser.parse_args()

    config_path = args.config
    if not config_path.is_absolute():
        config_path = (_REPO_ROOT / config_path).resolve()

    if args.distill:
        cmd_distill(args.task, config_path=config_path)
        return
    if args.init is not None:
        cmd_init(args.init, force=args.yes, config_path=config_path)
        return

    parser.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
