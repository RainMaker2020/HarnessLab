"""Tests for core/git_paths.py — changed paths relative to a nested workspace."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from harness.git.git_paths import git_changed_paths_relative_to_workspace  # noqa: E402


def _git_init_with_commit(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.co"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_git_changed_paths_nested_workspace(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    ws = repo / "project" / "ws"
    ws.mkdir(parents=True)
    (ws / "tracked.txt").write_text("v1", encoding="utf-8")
    _git_init_with_commit(repo)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    (ws / "tracked.txt").write_text("v2", encoding="utf-8")

    out = git_changed_paths_relative_to_workspace(ws)
    assert out is not None
    assert "tracked.txt" in out


def test_git_changed_paths_ignores_files_outside_workspace(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    ws = repo / "project" / "ws"
    ws.mkdir(parents=True)
    (ws / "in.txt").write_text("a", encoding="utf-8")
    _git_init_with_commit(repo)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    (repo / "outside.txt").write_text("x", encoding="utf-8")
    (ws / "in.txt").write_text("b", encoding="utf-8")

    out = git_changed_paths_relative_to_workspace(ws)
    assert out is not None
    assert "in.txt" in out
    assert not any("outside" in p for p in out)


def test_git_changed_paths_returns_none_outside_repo(tmp_path: Path) -> None:
    orphan = tmp_path / "not_a_repo"
    orphan.mkdir()
    assert git_changed_paths_relative_to_workspace(orphan) is None
