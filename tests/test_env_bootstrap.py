"""Tests for .env loading at harness startup."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))


def test_load_harness_env_calls_dotenv_with_repo_root_env_file():
    from env_bootstrap import load_harness_env

    with patch("dotenv.load_dotenv") as mock_load:
        load_harness_env()
    mock_load.assert_called_once()
    kwargs = mock_load.call_args.kwargs
    assert kwargs.get("override") is False
    path = kwargs.get("dotenv_path")
    assert path is not None
    assert path.name == ".env"
    # Repo root = parent of core/ (where env_bootstrap.py lives)
    assert path.parent == Path(__file__).resolve().parent.parent
