import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from evaluator import Evaluator, EvalResult


class FakeConfig:
    build_command = "echo 'ok'"
    workspace_dir = Path("/tmp/workspace")


def test_evalresult_passed_on_exit_zero():
    config = FakeConfig()
    evaluator = Evaluator(config)
    with patch("evaluator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        result = evaluator.run()
    assert result.passed is True
    assert result.exit_code == 0
    assert "ok" in result.output


def test_evalresult_failed_on_nonzero_exit():
    config = FakeConfig()
    evaluator = Evaluator(config)
    with patch("evaluator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="build failed")
        result = evaluator.run()
    assert result.passed is False
    assert result.exit_code == 1
    assert "build failed" in result.output


def test_evalresult_captures_both_stdout_and_stderr():
    config = FakeConfig()
    evaluator = Evaluator(config)
    with patch("evaluator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="compiled\n", stderr="warning: unused var")
        result = evaluator.run()
    assert "compiled" in result.output
    assert "warning" in result.output
