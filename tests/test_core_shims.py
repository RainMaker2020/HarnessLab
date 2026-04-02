"""Tests for ``core/evaluator_cli.py`` and ``core/mcp_server.py`` shims (stable import paths)."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO = Path(__file__).resolve().parent.parent
_CORE = _REPO / "core"


def test_core_evaluator_cli_shim_reexports_main() -> None:
    sys.path.insert(0, str(_CORE))
    import evaluator_cli as shim  # noqa: WPS433

    assert callable(shim.main)


def test_core_mcp_server_shim_reexports_harness_symbols() -> None:
    sys.path.insert(0, str(_CORE))
    import mcp_server as shim  # noqa: WPS433

    assert callable(shim.harness_next_task_text)
    assert callable(shim.harness_eval_text)
    assert callable(shim.harness_commit_impl)
    assert callable(shim.main)


def test_core_evaluator_cli_main_block_calls_harness_main() -> None:
    with patch("harness.evaluator_cli.main") as mock_main:
        runpy.run_path(str(_CORE / "evaluator_cli.py"), run_name="__main__")
    mock_main.assert_called_once()


def test_core_mcp_server_main_block_calls_harness_main() -> None:
    with patch("harness.mcp_server.main") as mock_main:
        runpy.run_path(str(_CORE / "mcp_server.py"), run_name="__main__")
    mock_main.assert_called_once()
