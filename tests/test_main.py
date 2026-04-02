"""Tests for manage.py CLI (e.g. ``--init``)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "core"))

from harness.exceptions import HarnessError


def test_main_init_invokes_scaffolder():
    import manage as main_mod

    with patch.object(main_mod, "Scaffolder") as MockScaff, patch.object(main_mod, "ModelRouter") as MockRoute:
        with patch.object(sys, "argv", ["prog", "--init", "my idea", "-y"]):
            main_mod.main()
        MockScaff.assert_called_once()
        cfg_passed = MockScaff.call_args[0][0]
        MockRoute.assert_called_once_with(cfg_passed)
        MockScaff.return_value.run.assert_called_once_with("my idea", force=True)


def test_main_init_harness_error_exits_with_code_1():
    import manage as main_mod

    with patch.object(main_mod, "Scaffolder") as MockScaff, patch.object(main_mod, "ModelRouter"):
        MockScaff.return_value.run.side_effect = HarnessError("bad")
        with patch.object(sys, "argv", ["prog", "--init", "x"]):
            with pytest.raises(SystemExit) as ei:
                main_mod.main()
            assert ei.value.code == 1


def test_main_no_subcommand_prints_help_and_exits_2():
    import manage as main_mod

    with patch.object(sys, "argv", ["prog"]):
        with pytest.raises(SystemExit) as ei:
            main_mod.main()
        assert ei.value.code == 2


def test_main_distill_invokes_trajectory_logger(tmp_path: Path):
    import manage as main_mod

    _write_manage_harness(tmp_path)
    ws = tmp_path / "workspace"

    def _git_init() -> None:
        subprocess.run(["git", "init"], cwd=ws, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "d@d.co"],
            cwd=ws,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "d"],
            cwd=ws,
            check=True,
            capture_output=True,
        )
        (ws / "f.txt").write_text("v1", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=ws, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "c0"], cwd=ws, check=True, capture_output=True)

    _git_init()
    (ws / "f.txt").write_text("v2", encoding="utf-8")

    out_jsonl = tmp_path / "docs" / "traj.jsonl"
    with patch.object(main_mod, "_REPO_ROOT", tmp_path):
        with patch.object(sys, "argv", ["prog", "--distill", "--task", "TASK_07"]):
            main_mod.main()

    assert out_jsonl.is_file()
    payload = out_jsonl.read_text(encoding="utf-8").strip().splitlines()[-1]
    row = json.loads(payload)
    assert row["task_id"] == "TASK_07"
    assert "v2" in row["output_git_diff"] or "f.txt" in row["output_git_diff"]


def test_main_distill_exits_when_export_path_missing(tmp_path: Path):
    import manage as main_mod

    _write_manage_harness(tmp_path, include_distill_export=False)
    with patch.object(main_mod, "_REPO_ROOT", tmp_path):
        with patch.object(sys, "argv", ["prog", "--distill"]):
            with pytest.raises(SystemExit) as ei:
                main_mod.main()
            assert ei.value.code == 1


def _write_manage_harness(root: Path, *, include_distill_export: bool = True) -> None:
    (root / "ARCHITECTURE.md").write_text("a", encoding="utf-8")
    (root / "SPEC.md").write_text("s", encoding="utf-8")
    (root / "workspace").mkdir()
    (root / "docs").mkdir()
    (root / "docs" / "history.json").write_text("[]", encoding="utf-8")
    extra = ""
    if include_distill_export:
        extra = "\n  distillation_export: ./docs/traj.jsonl\n"
    (root / "harness.yaml").write_text(
        f"""
paths:
  workspace_dir: ./workspace
  architecture_doc: ./ARCHITECTURE.md
  specification_doc: ./SPEC.md
  plan_file: ./workspace/PLAN.md
  history_log: ./docs/history.json{extra}
evaluation:
  build_command: "echo ok"
  strategy: exit_code
orchestration:
  mode: linear
  max_retries_per_task: 1
  interactive_mode: false
  auto_rollback: true
  distillation_mode: false
  test_first: false
  contract_negotiation_max_retries: 1
""",
        encoding="utf-8",
    )
