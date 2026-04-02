"""Tests for ``DockerManager`` (runtime sandbox) — subprocess boundaries mocked."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from harness.exceptions import HarnessError  # noqa: E402
from harness.runtime.sandbox import DockerManager  # noqa: E402


class _FakeDockerConfig:
    """Minimal config surface for DockerManager (no MagicMock truthiness pitfalls)."""

    def __init__(self) -> None:
        self.project = type("P", (), {"name": "My Project!"})()
        self.workspace_dir = Path("/tmp/harness-ws")
        self.docker_image = "custom:image"
        self.docker_memory_limit = "512m"
        self.docker_network_access = False


def _cfg() -> _FakeDockerConfig:
    return _FakeDockerConfig()


def test_docker_start_success_records_container_id() -> None:
    ui = MagicMock()
    dm = DockerManager(_cfg(), ui)
    proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="container-id-full\n", stderr=""
    )
    with patch("harness.runtime.sandbox.subprocess.run", return_value=proc) as mock_run:
        dm.start()
    assert dm._container_id == "container-id-full"
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "docker" in cmd and "--network" in cmd and "none" in cmd
    ui.info.assert_called()


def test_docker_start_raises_on_nonzero_exit() -> None:
    ui = MagicMock()
    dm = DockerManager(_cfg(), ui)
    proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
    with patch("harness.runtime.sandbox.subprocess.run", return_value=proc):
        with pytest.raises(HarnessError, match="Docker container failed"):
            dm.start()


def test_docker_start_raises_when_docker_missing() -> None:
    ui = MagicMock()
    dm = DockerManager(_cfg(), ui)
    with patch("harness.runtime.sandbox.subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(HarnessError, match="Docker executable not found"):
            dm.start()


def test_docker_start_raises_on_timeout() -> None:
    ui = MagicMock()
    dm = DockerManager(_cfg(), ui)
    with patch(
        "harness.runtime.sandbox.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=60),
    ):
        with pytest.raises(HarnessError, match="timed out"):
            dm.start()


def test_exec_claude_requires_start() -> None:
    dm = DockerManager(_cfg(), MagicMock())
    with pytest.raises(HarnessError, match="not running"):
        dm.exec_claude(Path("/tmp/prompt.txt"), ["--model", "x"])


def test_exec_claude_runs_docker_exec(tmp_path: Path) -> None:
    ui = MagicMock()
    dm = DockerManager(_cfg(), ui)
    dm._container_id = "cid123"
    p = tmp_path / "p.txt"
    p.write_text("hello", encoding="utf-8")
    proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="out", stderr="")
    with patch("harness.runtime.sandbox.subprocess.run", return_value=proc) as mock_run:
        out = dm.exec_claude(p, ["-m", "m"])
    assert out.returncode == 0
    mock_run.assert_called_once()
    assert mock_run.call_args[0][0][:3] == ["docker", "exec", "cid123"]


def test_exec_claude_synthetic_failure_on_subprocess_error() -> None:
    ui = MagicMock()
    dm = DockerManager(_cfg(), ui)
    dm._container_id = "cid"
    p = Path("/nonexistent-will-not-be-read")  # noqa: S108 — patched read
    with patch.object(Path, "read_text", return_value="x"):
        with patch(
            "harness.runtime.sandbox.subprocess.run",
            side_effect=subprocess.SubprocessError("x"),
        ):
            r = dm.exec_claude(p, [])
    assert r.returncode == 1
    assert "docker exec failed" in r.stderr


def test_stop_is_noop_without_start() -> None:
    dm = DockerManager(_cfg(), MagicMock())
    with patch("harness.runtime.sandbox.subprocess.run") as mock_run:
        dm.stop()
    mock_run.assert_not_called()


def test_stop_removes_container() -> None:
    ui = MagicMock()
    dm = DockerManager(_cfg(), ui)
    dm._container_id = "abc123"
    with patch("harness.runtime.sandbox.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")):
        dm.stop()
    assert dm._container_id is None
