"""Git isolation for Sub-Orchestrators: separate repo per module OR linked git worktree."""

from __future__ import annotations

import subprocess
from pathlib import Path

from harness.exceptions import HarnessError


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise HarnessError(
            "git executable not found. Install git and ensure it is on PATH."
        ) from exc


def _ensure_initial_commit(repo_dir: Path) -> None:
    """Guarantee at least one commit so `git worktree add ... HEAD` works."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    if not (repo_dir / ".git").exists():
        r = _run_git(repo_dir, "init")
        if r.returncode != 0:
            raise HarnessError(f"git init failed in {repo_dir}:\n{r.stderr}")
        _run_git(repo_dir, "config", "user.email", "harness@lab.local")
        _run_git(repo_dir, "config", "user.name", "HarnessLab")
        keep = repo_dir / ".gitkeep"
        keep.parent.mkdir(parents=True, exist_ok=True)
        keep.touch()
        _run_git(repo_dir, "add", ".")
        _run_git(repo_dir, "commit", "-m", "chore: harness primary workspace baseline")
        return
    count = _run_git(repo_dir, "rev-list", "--count", "HEAD").stdout.strip()
    if count == "0":
        keep = repo_dir / ".gitkeep"
        keep.touch()
        _run_git(repo_dir, "add", ".")
        _run_git(repo_dir, "commit", "-m", "chore: harness primary workspace baseline")


def provision_subrepo_workspace(module_dir: Path) -> Path:
    """Isolated environment: dedicated directory with its own git repository."""
    module_dir.mkdir(parents=True, exist_ok=True)
    if (module_dir / ".git").exists():
        return module_dir.resolve()
    r = _run_git(module_dir, "init")
    if r.returncode != 0:
        raise HarnessError(f"git init failed in {module_dir}:\n{r.stderr}")
    _run_git(module_dir, "config", "user.email", "harness@lab.local")
    _run_git(module_dir, "config", "user.name", "HarnessLab")
    (module_dir / ".gitkeep").touch()
    _run_git(module_dir, "add", ".")
    _run_git(module_dir, "commit", "-m", "chore: init module sub-workspace")
    return module_dir.resolve()


def provision_worktree_workspace(main_repo: Path, worktree_path: Path, branch: str) -> Path:
    """Isolated environment: git worktree linked to primary repo (sibling checkout, not nested)."""
    main_repo = main_repo.resolve()
    worktree_path = worktree_path.resolve()
    _ensure_initial_commit(main_repo)

    if (worktree_path / ".git").exists() or (worktree_path.is_dir() and any(worktree_path.iterdir())):
        # Idempotent: already linked or populated
        return worktree_path

    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    r = _run_git(
        main_repo,
        "worktree",
        "add",
        str(worktree_path),
        "-b",
        branch,
        "HEAD",
    )
    if r.returncode != 0:
        r2 = _run_git(main_repo, "worktree", "add", str(worktree_path), branch)
        if r2.returncode != 0:
            raise HarnessError(
                f"git worktree add failed for {worktree_path} (branch {branch}).\n"
                f"First attempt:\n{r.stderr}\nSecond attempt:\n{r2.stderr}"
            )
    return worktree_path
