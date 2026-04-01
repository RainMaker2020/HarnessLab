import pytest
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from main import HistoryManager


@pytest.fixture
def history_file(tmp_path):
    f = tmp_path / "docs" / "history.json"
    f.parent.mkdir()
    f.write_text("[]")
    return f


def test_append_adds_entry(history_file):
    mgr = HistoryManager(history_file)
    mgr.append({"task_id": "TASK_01", "attempt": 1, "claude_exit_code": 1})
    data = json.loads(history_file.read_text())
    assert len(data) == 1
    assert data[0]["task_id"] == "TASK_01"


def test_append_accumulates_entries(history_file):
    mgr = HistoryManager(history_file)
    mgr.append({"task_id": "TASK_01", "attempt": 1})
    mgr.append({"task_id": "TASK_01", "attempt": 2})
    data = json.loads(history_file.read_text())
    assert len(data) == 2


def test_last_failure_returns_most_recent_for_task(history_file):
    mgr = HistoryManager(history_file)
    mgr.append({"task_id": "TASK_01", "attempt": 1, "claude_exit_code": 1})
    mgr.append({"task_id": "TASK_01", "attempt": 2, "claude_exit_code": 1})
    last = mgr.last_failure("TASK_01")
    assert last["attempt"] == 2


def test_last_failure_returns_none_for_unknown_task(history_file):
    mgr = HistoryManager(history_file)
    assert mgr.last_failure("TASK_99") is None


def test_last_failure_only_matches_correct_task(history_file):
    mgr = HistoryManager(history_file)
    mgr.append({"task_id": "TASK_01", "attempt": 1})
    mgr.append({"task_id": "TASK_02", "attempt": 1})
    last = mgr.last_failure("TASK_02")
    assert last["task_id"] == "TASK_02"


def test_history_manager_creates_file_if_missing(tmp_path):
    f = tmp_path / "docs" / "history.json"
    mgr = HistoryManager(f)
    assert f.exists()
    assert json.loads(f.read_text()) == []
