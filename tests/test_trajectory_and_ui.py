"""Tests for trajectory logging and ObservationDeck (runtime UI)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from harness.runtime.trajectory_logger import (  # noqa: E402
    TrajectoryLogger,
    record_task_completion,
)
from harness.runtime.ui import ObservationDeck  # noqa: E402


def test_trajectory_logger_append_writes_jsonl_and_callback(tmp_path: Path) -> None:
    export = tmp_path / "nested" / "out.jsonl"
    seen: list[dict] = []

    def on_record(rec: dict) -> None:
        seen.append(rec)

    TrajectoryLogger(export).append("TASK_01", "prompt text", "diff --git", on_record=on_record)
    assert export.is_file()
    line = export.read_text(encoding="utf-8").strip().splitlines()[0]
    data = json.loads(line)
    assert data["task_id"] == "TASK_01"
    assert data["input"] == "prompt text"
    assert data["output_git_diff"] == "diff --git"
    assert "timestamp" in data
    assert seen and seen[0] == data


def test_record_task_completion_delegates_to_logger(tmp_path: Path) -> None:
    p = tmp_path / "t.jsonl"
    record_task_completion(p, "T2", "p", "d", on_record=None)
    assert "T2" in p.read_text(encoding="utf-8")


def test_observation_deck_methods_call_console() -> None:
    ui = ObservationDeck()
    with patch.object(ui._console, "print") as mock_print:
        ui.harness_started()
        ui.master_epic_started(Path("/tmp/EPIC.md"))
        ui.epic_module_start("M1", "Title")
        ui.epic_module_complete("M1", "Title")
        ui.epic_all_done()
        ui.task_start("TASK_01", "Do thing")
        ui.attempt_start(2, 3)
        ui.baseline("abcdef1234567890")
        ui.prompt_written(".harness_prompt.md")
        ui.executing("TASK_01")
        ui.success("TASK_01")
        ui.failure(1, "eval")
        ui.sos("TASK_01", "out", "err")
        ui.circuit_breaker("TASK_01", 3)
        ui.all_done()
        ui.workspace_initialized()
        ui.fatal_error("stop")
        ui.info("msg")
        ui.override_resumed()
        ui.contract_round(1, 3, "TASK_01")
        ui.contract_approved("TASK_01")
        ui.contract_rejected("TASK_01", "x" * 600)
        ui.contract_human_pause("TASK_01")
    assert mock_print.call_count >= 20


def test_interactive_pause_commit_rollback_override(monkeypatch: pytest.MonkeyPatch) -> None:
    ui = ObservationDeck()
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "c")
    assert ui.interactive_pause("T1") == "commit"

    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "r")
    assert ui.interactive_pause("T2") == "rollback"

    _seq = iter(["o", ""])

    def _inp(*_a: object, **_k: object) -> str:
        return next(_seq)

    monkeypatch.setattr("builtins.input", _inp)
    with patch.object(ui._console, "print"):
        assert ui.interactive_pause("T3") == "override_done"
