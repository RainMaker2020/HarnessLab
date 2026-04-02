"""Tests for git worktree / subrepo isolation helpers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from harness.git.git_isolation import (  # noqa: E402
    provision_subrepo_workspace,
    provision_worktree_workspace,
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)


def test_provision_subrepo_workspace_creates_repo(tmp_path: Path) -> None:
    mod = tmp_path / "module_a"
    out = provision_subrepo_workspace(mod)
    assert out == mod.resolve()
    assert (mod / ".git").is_dir()
    assert (mod / ".gitkeep").exists()
    r = _git(mod, "log", "-1", "--oneline")
    assert r.returncode == 0
    assert "init module" in r.stdout


def test_provision_subrepo_workspace_idempotent_when_git_exists(tmp_path: Path) -> None:
    mod = tmp_path / "module_b"
    mod.mkdir()
    _git(mod, "init")
    _git(mod, "config", "user.email", "t@test.local")
    _git(mod, "config", "user.name", "t")
    (mod / "f.txt").write_text("1", encoding="utf-8")
    _git(mod, "add", ".")
    _git(mod, "commit", "-m", "first")
    out = provision_subrepo_workspace(mod)
    assert out == mod.resolve()
    r = _git(mod, "rev-list", "--count", "HEAD")
    assert r.stdout.strip() == "1"


def test_provision_worktree_workspace_adds_linked_checkout(tmp_path: Path) -> None:
    main = tmp_path / "main_repo"
    main.mkdir()
    _git(main, "init")
    _git(main, "config", "user.email", "t@test.local")
    _git(main, "config", "user.name", "t")
    (main / "README.md").write_text("# M", encoding="utf-8")
    _git(main, "add", ".")
    _git(main, "commit", "-m", "base")

    wt = tmp_path / "wt_feature"
    path = provision_worktree_workspace(main, wt, "feature-branch")
    assert path.resolve() == wt.resolve()
    assert (wt / "README.md").read_text(encoding="utf-8").startswith("#")


def test_provision_worktree_workspace_second_call_is_idempotent(tmp_path: Path) -> None:
    main = tmp_path / "main_repo2"
    main.mkdir()
    _git(main, "init")
    _git(main, "config", "user.email", "t@test.local")
    _git(main, "config", "user.name", "t")
    (main / "x.txt").write_text("x", encoding="utf-8")
    _git(main, "add", ".")
    _git(main, "commit", "-m", "c1")

    wt = tmp_path / "wt2"
    p1 = provision_worktree_workspace(main, wt, "b1")
    p2 = provision_worktree_workspace(main, wt, "b1")
    assert p1 == p2
