#!/usr/bin/env python3
"""Smoke-check MCP tool helpers (no stdio client). Run from repo root."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "core"))

from env_bootstrap import load_harness_env  # noqa: E402
from mcp_server import (  # noqa: E402
    _load_config,
    harness_next_task_text,
    harness_progress_text,
)


def main() -> None:
    load_harness_env()
    cfg = _load_config()
    print("=== harness_next_task ===")
    print(harness_next_task_text(cfg))
    print("=== harness_progress (first 500 chars) ===")
    text = harness_progress_text(cfg)
    print(text[:500] + ("..." if len(text) > 500 else ""))
    print("=== OK ===")


if __name__ == "__main__":
    main()
