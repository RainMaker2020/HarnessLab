"""Tests for core/mcp_server.py tool helpers (no live Playwright/LLM)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from harness.eval.evaluator import EvalResult  # noqa: E402
from harness.exceptions import HarnessError  # noqa: E402
from harness.config.harness_config import HarnessConfig  # noqa: E402
import mcp_server  # noqa: E402


def _write_minimal_harness(root: Path) -> Path:
    """Minimal harness.yaml for isolated tests."""
    ws = root / "ws"
    ws.mkdir(parents=True)
    (ws / "PLAN.md").write_text(
        "- [ ] TASK_01: First task\n- [ ] TASK_02: Second\n", encoding="utf-8"
    )
    (ws / "PROGRESS.md").write_text("# Progress\nok\n", encoding="utf-8")
    (ws / "a.md").write_text("x", encoding="utf-8")
    (ws / "s.md").write_text("y", encoding="utf-8")
    (ws / "history.json").write_text("[]", encoding="utf-8")
    yml = root / "harness.yaml"
    yml.write_text(
        """
project:
  name: test
  version: "1"
  env: test
paths:
  workspace_dir: "./ws"
  architecture_doc: "./ws/a.md"
  specification_doc: "./ws/s.md"
  plan_file: "./ws/PLAN.md"
  history_log: "./ws/history.json"
evaluation:
  build_command: "echo ok"
  strategy: exit_code
runtime:
  mode: local
  image: img
  memory_limit: 2g
  network_access: false
orchestration:
  mode: linear
  max_retries_per_task: 3
  interactive_mode: false
  auto_rollback: true
  distillation_mode: false
  test_first: false
  contract_negotiation_max_retries: 3
""",
        encoding="utf-8",
    )
    return yml


def test_harness_next_task_text(tmp_path: Path) -> None:
    yml = _write_minimal_harness(tmp_path)
    cfg = HarnessConfig.from_yaml(yml)
    out = mcp_server.harness_next_task_text(cfg)
    assert "TASK_01" in out
    assert "First task" in out


def test_harness_progress_text(tmp_path: Path) -> None:
    yml = _write_minimal_harness(tmp_path)
    cfg = HarnessConfig.from_yaml(yml)
    assert mcp_server.harness_progress_text(cfg).startswith("# Progress")


def test_harness_eval_text_uses_verdict(tmp_path: Path) -> None:
    yml = _write_minimal_harness(tmp_path)
    cfg = HarnessConfig.from_yaml(yml)

    fake = EvalResult(passed=True, output="ok\nAPPROVE", exit_code=0)
    with patch("harness.mcp_server.run_playwright_eval", return_value=fake):
        text = mcp_server.harness_eval_text(cfg, "TASK_01")
    assert "VERDICT: APPROVE" in text

    fake_fail = EvalResult(passed=False, output="bad\nREJECT", exit_code=1)
    with patch("harness.mcp_server.run_playwright_eval", return_value=fake_fail):
        text = mcp_server.harness_eval_text(cfg, "TASK_01")
    assert "VERDICT: REJECT" in text


def test_harness_eval_text_task_mismatch(tmp_path: Path) -> None:
    yml = _write_minimal_harness(tmp_path)
    cfg = HarnessConfig.from_yaml(yml)
    out = mcp_server.harness_eval_text(cfg, "TASK_99")
    assert "mismatch" in out.lower()
    with patch("harness.mcp_server.run_playwright_eval") as mock_eval:
        mcp_server.harness_eval_text(cfg, "TASK_99")
    mock_eval.assert_not_called()


def test_plan_guard_missing_plan_file(tmp_path: Path) -> None:
    yml = _write_minimal_harness(tmp_path)
    cfg = HarnessConfig.from_yaml(yml)
    Path(cfg.plan_file).unlink()
    assert "not found" in mcp_server.harness_next_task_text(cfg).lower()
    assert "not found" in mcp_server.harness_commit_impl(cfg, "TASK_01", "m", tmp_path).lower()


def test_harness_commit_blocks_on_task_mismatch(tmp_path: Path) -> None:
    yml = _write_minimal_harness(tmp_path)
    cfg = HarnessConfig.from_yaml(yml)
    out = mcp_server.harness_commit_impl(cfg, "TASK_99", "msg", tmp_path)
    assert "mismatch" in out.lower()


def test_harness_commit_blocks_when_eval_fails(tmp_path: Path) -> None:
    yml = _write_minimal_harness(tmp_path)
    cfg = HarnessConfig.from_yaml(yml)
    fake = EvalResult(passed=False, output="REJECT", exit_code=1)
    with patch("harness.mcp_server.run_playwright_eval", return_value=fake):
        out = mcp_server.harness_commit_impl(cfg, "TASK_01", "msg", tmp_path)
    assert "blocked" in out.lower()
    assert "VERDICT: REJECT" in out


def test_harness_commit_succeeds_after_passing_eval(tmp_path: Path) -> None:
    yml = _write_minimal_harness(tmp_path)
    cfg = HarnessConfig.from_yaml(yml)

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.co"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    (tmp_path / "ws" / "after_init.txt").write_text("staged-by-harness", encoding="utf-8")

    fake = EvalResult(passed=True, output="ok\nAPPROVE", exit_code=0)
    with patch("harness.mcp_server.run_playwright_eval", return_value=fake):
        out = mcp_server.harness_commit_impl(cfg, "TASK_01", "task commit", tmp_path)
    assert "Committed TASK_01" in out
    assert "task commit" in out or "Committed" in out


def test_load_config_missing_raises() -> None:
    with pytest.raises(HarnessError):
        mcp_server._load_config(Path("/nonexistent/harness.yaml"))
