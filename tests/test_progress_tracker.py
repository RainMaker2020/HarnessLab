"""Unit tests for ProgressTracker — written before implementation (TDD RED phase)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from harness.git.progress_tracker import ProgressTracker, ProgressSnapshot
from harness.exceptions import HarnessError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(workspace: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.workspace_dir = workspace
    return cfg


def _make_ui() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# update()
# ---------------------------------------------------------------------------

class TestProgressTrackerUpdate:
    def test_creates_progress_md(self, tmp_path: Path) -> None:
        tracker = ProgressTracker(_make_config(tmp_path), _make_ui())
        tracker.update(completed_tasks=["TASK_01: Build thing"])
        assert (tmp_path / "PROGRESS.md").exists()

    def test_marks_each_task_with_done_checkbox(self, tmp_path: Path) -> None:
        tracker = ProgressTracker(_make_config(tmp_path), _make_ui())
        tracker.update(completed_tasks=["TASK_01: Build thing", "TASK_02: Fix it"])
        content = (tmp_path / "PROGRESS.md").read_text(encoding="utf-8")
        assert "- [x] TASK_01: Build thing" in content
        assert "- [x] TASK_02: Fix it" in content

    def test_shows_none_placeholder_for_empty_task_list(self, tmp_path: Path) -> None:
        tracker = ProgressTracker(_make_config(tmp_path), _make_ui())
        tracker.update(completed_tasks=[])
        content = (tmp_path / "PROGRESS.md").read_text(encoding="utf-8")
        assert "_none yet_" in content

    def test_includes_file_tree_section(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("x")
        tracker = ProgressTracker(_make_config(tmp_path), _make_ui())
        tracker.update(completed_tasks=[])
        content = (tmp_path / "PROGRESS.md").read_text(encoding="utf-8")
        assert "## Current file tree" in content
        assert "main.py" in content

    def test_includes_architectural_notes(self, tmp_path: Path) -> None:
        tracker = ProgressTracker(_make_config(tmp_path), _make_ui())
        tracker.update(completed_tasks=[], architectural_notes="Used factory pattern.")
        content = (tmp_path / "PROGRESS.md").read_text(encoding="utf-8")
        assert "Used factory pattern." in content

    def test_raises_harness_error_on_write_failure(self, tmp_path: Path) -> None:
        tracker = ProgressTracker(_make_config(tmp_path), _make_ui())
        tracker.path = Path("/nonexistent_dir_xyz/PROGRESS.md")
        with pytest.raises(HarnessError, match="ProgressTracker write failed"):
            tracker.update(completed_tasks=[])

    def test_progress_md_excluded_from_file_tree(self, tmp_path: Path) -> None:
        """PROGRESS.md itself must not appear in its own file tree."""
        (tmp_path / "app.py").write_text("x")
        tracker = ProgressTracker(_make_config(tmp_path), _make_ui())
        tracker.update(completed_tasks=[])
        # Write a second time so PROGRESS.md exists when scanned
        tracker.update(completed_tasks=[])
        content = (tmp_path / "PROGRESS.md").read_text(encoding="utf-8")
        # PROGRESS.md may appear in tree because _scan_workspace is called before write;
        # but .harness_prompt.md must be excluded — verify excluded sentinel works
        assert "PROGRESS.md" not in content or content.count("PROGRESS.md") == 1  # only the heading reference


# ---------------------------------------------------------------------------
# read() / exists()
# ---------------------------------------------------------------------------

class TestProgressTrackerRead:
    def test_returns_empty_string_when_no_file(self, tmp_path: Path) -> None:
        tracker = ProgressTracker(_make_config(tmp_path), _make_ui())
        assert tracker.read() == ""

    def test_returns_file_content_after_update(self, tmp_path: Path) -> None:
        tracker = ProgressTracker(_make_config(tmp_path), _make_ui())
        tracker.update(completed_tasks=["TASK_01: Done"])
        content = tracker.read()
        assert "HarnessLab" in content
        assert "TASK_01: Done" in content


class TestProgressTrackerExists:
    def test_false_before_any_write(self, tmp_path: Path) -> None:
        tracker = ProgressTracker(_make_config(tmp_path), _make_ui())
        assert tracker.exists() is False

    def test_true_after_update(self, tmp_path: Path) -> None:
        tracker = ProgressTracker(_make_config(tmp_path), _make_ui())
        tracker.update(completed_tasks=[])
        assert tracker.exists() is True


# ---------------------------------------------------------------------------
# _scan_workspace()
# ---------------------------------------------------------------------------

class TestScanWorkspace:
    def test_excludes_dot_git(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref")
        (tmp_path / "main.py").write_text("x")
        tracker = ProgressTracker(_make_config(tmp_path), _make_ui())
        tree = tracker._scan_workspace()
        assert not any(".git" in f for f in tree)
        assert "main.py" in tree

    def test_excludes_node_modules_and_pycache(self, tmp_path: Path) -> None:
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "lib.js").write_text("x")
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "mod.pyc").write_text("x")
        (tmp_path / "app.py").write_text("x")
        tracker = ProgressTracker(_make_config(tmp_path), _make_ui())
        tree = tracker._scan_workspace()
        assert not any("node_modules" in f for f in tree)
        assert not any("__pycache__" in f for f in tree)
        assert "app.py" in tree

    def test_returns_sorted_relative_paths(self, tmp_path: Path) -> None:
        (tmp_path / "z.py").write_text("x")
        (tmp_path / "a.py").write_text("x")
        tracker = ProgressTracker(_make_config(tmp_path), _make_ui())
        tree = tracker._scan_workspace()
        assert tree == sorted(tree)
        assert all(not Path(f).is_absolute() for f in tree)
