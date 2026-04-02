"""Integration tests for core/hooks/post_write_gate.py (subprocess, real exit codes)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _post_write_gate_script() -> Path:
    return Path(__file__).resolve().parent.parent / "core" / "hooks" / "post_write_gate.py"


def _write_minimal_harness(
    root: Path,
    *,
    build_cmd: str = "echo ok",
) -> None:
    (root / "harness.yaml").write_text(
        f"""paths:
  workspace_dir: "./workspace"
evaluation:
  build_command: "{build_cmd}"
""",
        encoding="utf-8",
    )


def test_post_write_gate_exits_0_when_build_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    _write_minimal_harness(tmp_path, build_cmd="echo ok")
    (ws / "touch.txt").write_text("x", encoding="utf-8")

    monkeypatch.setenv("HARNESS_POST_WRITE_GATE_ROOT", str(tmp_path))
    monkeypatch.setenv("CLAUDE_TOOL_INPUT", json.dumps({"path": "workspace/touch.txt"}))

    proc = subprocess.run(
        [sys.executable, str(_post_write_gate_script())],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_post_write_gate_exits_1_when_build_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    _write_minimal_harness(tmp_path, build_cmd="sh -c 'exit 1'")
    (ws / "bad.txt").write_text("x", encoding="utf-8")

    monkeypatch.setenv("HARNESS_POST_WRITE_GATE_ROOT", str(tmp_path))
    monkeypatch.setenv("CLAUDE_TOOL_INPUT", json.dumps({"path": "workspace/bad.txt"}))

    proc = subprocess.run(
        [sys.executable, str(_post_write_gate_script())],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "BUILD FAILED" in (proc.stdout or "")


def test_post_write_gate_skips_when_path_outside_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "workspace").mkdir()
    _write_minimal_harness(tmp_path, build_cmd="sh -c 'exit 1'")

    monkeypatch.setenv("HARNESS_POST_WRITE_GATE_ROOT", str(tmp_path))
    monkeypatch.setenv("CLAUDE_TOOL_INPUT", json.dumps({"path": "README.md"}))

    proc = subprocess.run(
        [sys.executable, str(_post_write_gate_script())],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
