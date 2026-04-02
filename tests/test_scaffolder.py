"""Tests for Scaffolder."""

import subprocess
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from harness.exceptions import HarnessError
from harness.config.model_router import ModelRouter
from harness.planning.scaffolder import (
    SCAFFOLDER_SYSTEM_PROMPT,
    Scaffolder,
    _BEGIN_ARCH,
    _END_ARCH,
    _BEGIN_PLAN,
    _END_PLAN,
    _BEGIN_SPEC,
    _END_SPEC,
)


def _sample_stdout() -> str:
    return (
        f"{_BEGIN_ARCH}\n# Arch\nStack: X.\n{_END_ARCH}\n"
        f"{_BEGIN_SPEC}\n# Spec\nFeatures.\n{_END_SPEC}\n"
        f"{_BEGIN_PLAN}\n- [ ] TASK_01: first\n{_END_PLAN}\n"
    )


def test_system_prompt_constant():
    assert "Senior Architect for HarnessLab" in SCAFFOLDER_SYSTEM_PROMPT
    assert "Hater" in SCAFFOLDER_SYSTEM_PROMPT


def test_parse_triple_output():
    a, s, p = Scaffolder._parse_triple_output(_sample_stdout())
    assert "# Arch" in a
    assert "# Spec" in s
    assert "TASK_01" in p


def test_parse_triple_output_missing_raises():
    with pytest.raises(HarnessError, match="ARCHITECTURE"):
        Scaffolder._parse_triple_output("no delimiters here")


def test_existing_spec_conflicts(tmp_path):
    arch = tmp_path / "ARCHITECTURE.md"
    spec = tmp_path / "SPEC.md"
    arch.write_text("x")
    cfg = type(
        "C",
        (),
        {
            "architecture_doc": arch,
            "spec_doc": spec,
        },
    )()
    s = Scaffolder(cfg, ModelRouter(type("M", (), {"models": {}})()))
    assert s.existing_spec_conflicts() == [arch]
    spec.write_text("y")
    assert set(s.existing_spec_conflicts()) == {arch, spec}


def test_run_writes_files(tmp_path):
    arch = tmp_path / "ARCHITECTURE.md"
    spec = tmp_path / "SPEC.md"
    plan = tmp_path / "workspace" / "PLAN.md"
    cfg = type(
        "C",
        (),
        {
            "architecture_doc": arch,
            "spec_doc": spec,
            "plan_file": plan,
            "planner_timeout_seconds": 30,
        },
    )()
    router = ModelRouter(type("M", (), {"models": {"planner": "claude-sonnet-4-6"}})())

    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    proc.stdout = _sample_stdout()
    proc.stderr = ""

    with patch("harness.planning.scaffolder.subprocess.run", return_value=proc) as mock_run:
        Scaffolder(cfg, router).run("Build a thing", force=True)

    assert "# Arch" in arch.read_text()
    assert "# Spec" in spec.read_text()
    assert "TASK_01" in plan.read_text()
    mock_run.assert_called_once()
    call_args = mock_run.call_args
    cmd = call_args[0][0]
    assert cmd[0] == "claude"
    assert cmd[1] == "--print"
    assert cmd[-2:] == ["--model", "claude-sonnet-4-6"]
    assert "Build a thing" in cmd[2]


def _minimal_cfg(tmp_path):
    return type(
        "C",
        (),
        {
            "architecture_doc": tmp_path / "a.md",
            "spec_doc": tmp_path / "s.md",
            "plan_file": tmp_path / "p.md",
            "planner_timeout_seconds": 30,
        },
    )()


def test_invoke_planner_nonzero_exit_raises(tmp_path):
    cfg = _minimal_cfg(tmp_path)
    router = ModelRouter(type("M", (), {"models": {"planner": "p-model"}})())
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 1
    proc.stdout = ""
    proc.stderr = "boom"

    with patch("harness.planning.scaffolder.subprocess.run", return_value=proc):
        with pytest.raises(HarnessError, match="Scaffolder failed"):
            Scaffolder(cfg, router)._invoke_planner("x")


def test_invoke_planner_empty_stdout_raises(tmp_path):
    cfg = _minimal_cfg(tmp_path)
    router = ModelRouter(type("M", (), {"models": {"planner": "p-model"}})())
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    proc.stdout = "   "
    proc.stderr = ""

    with patch("harness.planning.scaffolder.subprocess.run", return_value=proc):
        with pytest.raises(HarnessError, match="empty output"):
            Scaffolder(cfg, router)._invoke_planner("x")


def test_invoke_planner_timeout_raises(tmp_path):
    cfg = _minimal_cfg(tmp_path)
    router = ModelRouter(type("M", (), {"models": {"planner": "p"}})())

    def _timeout(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd=["claude"], timeout=30)

    with patch("harness.planning.scaffolder.subprocess.run", side_effect=_timeout):
        with pytest.raises(HarnessError, match="timed out"):
            Scaffolder(cfg, router)._invoke_planner("x")


def test_invoke_planner_missing_claude_raises(tmp_path):
    cfg = _minimal_cfg(tmp_path)
    router = ModelRouter(type("M", (), {"models": {"planner": "p"}})())

    with patch("harness.planning.scaffolder.subprocess.run", side_effect=FileNotFoundError()):
        with pytest.raises(HarnessError, match="claude CLI not found"):
            Scaffolder(cfg, router)._invoke_planner("x")


def test_run_abort_when_existing_and_no_force(tmp_path):
    arch = tmp_path / "ARCHITECTURE.md"
    spec = tmp_path / "SPEC.md"
    plan = tmp_path / "workspace" / "PLAN.md"
    arch.write_text("old")
    cfg = type(
        "C",
        (),
        {
            "architecture_doc": arch,
            "spec_doc": spec,
            "plan_file": plan,
            "planner_timeout_seconds": 30,
        },
    )()
    router = ModelRouter(type("M", (), {"models": {}})())

    with pytest.raises(HarnessError, match="aborted"):
        Scaffolder(cfg, router).run("x", force=False, stdin=StringIO("no\n"))


def test_run_proceeds_when_user_types_yes(tmp_path):
    arch = tmp_path / "ARCHITECTURE.md"
    spec = tmp_path / "SPEC.md"
    plan = tmp_path / "workspace" / "PLAN.md"
    arch.write_text("old")
    cfg = type(
        "C",
        (),
        {
            "architecture_doc": arch,
            "spec_doc": spec,
            "plan_file": plan,
            "planner_timeout_seconds": 30,
        },
    )()
    router = ModelRouter(type("M", (), {"models": {}})())

    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    proc.stdout = _sample_stdout()
    proc.stderr = ""

    with patch("harness.planning.scaffolder.subprocess.run", return_value=proc):
        Scaffolder(cfg, router).run("idea", force=False, stdin=StringIO("yes\n"))

    assert "# Arch" in arch.read_text()


def test_run_empty_prompt_raises(tmp_path):
    cfg = type(
        "C",
        (),
        {
            "architecture_doc": tmp_path / "a.md",
            "spec_doc": tmp_path / "s.md",
            "plan_file": tmp_path / "p.md",
        },
    )()
    with pytest.raises(HarnessError, match="non-empty"):
        Scaffolder(cfg, ModelRouter(type("M", (), {"models": {}})())).run("   ", force=True)
