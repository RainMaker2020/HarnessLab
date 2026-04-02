#!/usr/bin/env python3
"""Shim: stable path `core/mcp_server.py` for MCP and docs — implementation in `harness.mcp_server`."""

from __future__ import annotations

import sys
from pathlib import Path

_CORE = Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from harness.mcp_server import (  # noqa: E402
    _load_config,
    harness_commit_impl,
    harness_eval_text,
    harness_next_task_text,
    harness_progress_text,
    main,
    mcp,
    run_playwright_eval,
)

__all__ = [
    "_load_config",
    "harness_commit_impl",
    "harness_eval_text",
    "harness_next_task_text",
    "harness_progress_text",
    "main",
    "mcp",
    "run_playwright_eval",
]

if __name__ == "__main__":
    main()
