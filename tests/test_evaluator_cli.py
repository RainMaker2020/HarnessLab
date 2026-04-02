"""Tests for ``harness.evaluator_cli`` — config resolution, evaluator wiring, exit codes."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from harness.eval.evaluator import EvalResult  # noqa: E402
from harness.exceptions import HarnessError  # noqa: E402


def test_main_exits_2_when_config_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import harness.evaluator_cli as ec

    missing = tmp_path / "nope.yaml"
    monkeypatch.setattr(ec, "_REPO", tmp_path)
    with patch.object(sys, "argv", ["evaluator_cli", "--config", str(missing.name)]):
        with pytest.raises(SystemExit) as ei:
            ec.main()
        assert ei.value.code == 2


def test_main_exits_2_on_harness_error_from_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import harness.evaluator_cli as ec

    (tmp_path / "harness.yaml").write_text("x: 1", encoding="utf-8")
    monkeypatch.setattr(ec, "_REPO", tmp_path)
    with patch.object(sys, "argv", ["evaluator_cli", "--config", "harness.yaml"]):
        with patch.object(ec.HarnessConfig, "from_yaml", side_effect=HarnessError("bad parse")):
            with pytest.raises(SystemExit) as ei:
                ec.main()
        assert ei.value.code == 2


def test_main_uses_playwright_visual_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import harness.evaluator_cli as ec

    _write_minimal_yaml(tmp_path)
    monkeypatch.setattr(ec, "_REPO", tmp_path)
    fake_eval = MagicMock()
    fake_eval.run.return_value = EvalResult(passed=True, output="VERDICT: APPROVE", exit_code=0)
    with patch.object(ec, "load_harness_env"):
        with patch.object(ec, "HarnessConfig") as HC:
            HC.from_yaml.return_value = MagicMock(workspace_dir=tmp_path / "ws")
            with patch.object(ec, "PlaywrightVisualEvaluator", return_value=fake_eval):
                with patch.object(ec, "git_changed_paths_relative_to_workspace", return_value=[]):
                    with patch.object(sys, "argv", ["evaluator_cli", "--playwright-visual", "TASK_01"]):
                        with pytest.raises(SystemExit) as ei:
                            ec.main()
                        assert ei.value.code == 0
    fake_eval.run.assert_called_once()


def test_main_build_evaluator_path_exits_1_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import harness.evaluator_cli as ec

    _write_minimal_yaml(tmp_path)
    monkeypatch.setattr(ec, "_REPO", tmp_path)
    fake_eval = MagicMock()
    fake_eval.run.return_value = EvalResult(passed=False, output="bad", exit_code=1)
    with patch.object(ec, "load_harness_env"):
        with patch.object(ec, "HarnessConfig") as HC:
            HC.from_yaml.return_value = MagicMock(workspace_dir=tmp_path / "ws")
            with patch.object(ec, "build_evaluator", return_value=fake_eval):
                with patch.object(ec, "git_changed_paths_relative_to_workspace", return_value=["a.ts"]):
                    with patch.object(sys, "argv", ["evaluator_cli", "TASK_99"]):
                        with pytest.raises(SystemExit) as ei:
                            ec.main()
                        assert ei.value.code == 1


def _write_minimal_yaml(root: Path) -> None:
    ws = root / "ws"
    ws.mkdir(parents=True)
    (root / "harness.yaml").write_text(
        """
paths:
  workspace_dir: "./ws"
  architecture_doc: "./ws/a.md"
  specification_doc: "./ws/s.md"
  plan_file: "./ws/PLAN.md"
  history_log: "./ws/history.json"
evaluation:
  build_command: "echo ok"
  strategy: exit_code
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
    (ws / "a.md").write_text("a", encoding="utf-8")
    (ws / "s.md").write_text("s", encoding="utf-8")
    (ws / "PLAN.md").write_text("- [ ] T1\n", encoding="utf-8")
    (ws / "history.json").write_text("[]", encoding="utf-8")
