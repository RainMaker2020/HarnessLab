#!/usr/bin/env python3
"""HarnessingLab entry point — linear Sub-Orchestrator or recursive Master Orchestrator."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from exceptions import HarnessError
from harness_config import HarnessConfig
from model_router import ModelRouter
from scaffolder import Scaffolder
from sub_orchestrator import (
    GitManager,
    HistoryManager,
    PlanParser,
    SubOrchestrator,
    Task,
    Worker,
    build_evaluator,
)
from ui import ObservationDeck

# Backward compatibility: tests and scripts expect `Orchestrator`.
Orchestrator = SubOrchestrator

__all__ = [
    "GitManager",
    "HistoryManager",
    "Orchestrator",
    "PlanParser",
    "SubOrchestrator",
    "Task",
    "Worker",
    "build_evaluator",
    "main",
]


def main() -> None:
    """Load harness.yaml and run linear or recursive orchestration."""
    config_path = Path(__file__).parent.parent / "harness.yaml"
    ui = ObservationDeck()

    parser = argparse.ArgumentParser(description="HarnessingLab — orchestrator or Level-0 scaffolder")
    parser.add_argument(
        "--init",
        metavar="PROMPT",
        help='Scaffold ARCHITECTURE.md, SPEC.md, and workspace/PLAN.md from an idea (requires harness.yaml)',
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="With --init, overwrite existing ARCHITECTURE.md / SPEC.md without confirmation",
    )
    args = parser.parse_args()

    if args.init is not None:
        if not config_path.exists():
            ui.fatal_error(f"harness.yaml not found at {config_path}")
            sys.exit(1)
        try:
            config = HarnessConfig.from_yaml(config_path)
            Scaffolder(config, ModelRouter(config)).run(args.init, force=args.yes)
            ui.info(
                f"Scaffolder wrote {config.architecture_doc}, {config.spec_doc}, and {config.plan_file}."
            )
        except HarnessError as exc:
            ui.fatal_error(str(exc))
            sys.exit(1)
        return

    if not config_path.exists():
        ui.fatal_error(f"harness.yaml not found at {config_path}")
        sys.exit(1)

    try:
        config = HarnessConfig.from_yaml(config_path)
        if config.orchestration_mode == "recursive":
            from master_orchestrator import MasterOrchestrator

            MasterOrchestrator(config, ui=ui).run()
        else:
            evaluator = build_evaluator(config)
            orchestrator = SubOrchestrator(config, evaluator=evaluator, ui=ui)
            orchestrator.run()
    except HarnessError as exc:
        ui.fatal_error(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
