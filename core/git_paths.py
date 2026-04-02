"""Git-tracked paths relative to a workspace directory (repo root may be an ancestor)."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _rel_under_workspace(git_root: Path, workspace: Path, path_from_git_root: str) -> str | None:
    """If path is under workspace, return path relative to workspace (posix slashes)."""
    workspace = workspace.resolve()
    candidate = (git_root / path_from_git_root).resolve()
    try:
        rel = candidate.relative_to(workspace)
    except ValueError:
        return None
    return str(rel).replace("\\", "/")


def git_changed_paths_relative_to_workspace(workspace: Path) -> list[str] | None:
    """
    Paths changed vs HEAD plus untracked (exclude-standard), restricted to files under ``workspace``.

    Uses ``git rev-parse --show-toplevel`` from ``workspace`` so it works when ``.git`` lives
    at the repository root and ``workspace`` is a subdirectory (e.g. ``project/workspace``).
    Returns None if not inside a git work tree or git commands fail.
    """
    workspace = workspace.resolve()
    r = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=workspace,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    git_root = Path(r.stdout.strip()).resolve()

    names: list[str] = []
    r_diff = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=git_root,
        capture_output=True,
        text=True,
    )
    if r_diff.returncode != 0:
        return None
    for line in r_diff.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        rel = _rel_under_workspace(git_root, workspace, line)
        if rel is not None:
            names.append(rel)

    r_untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=git_root,
        capture_output=True,
        text=True,
    )
    if r_untracked.returncode == 0:
        for line in r_untracked.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            rel = _rel_under_workspace(git_root, workspace, line)
            if rel is not None:
                names.append(rel)

    return sorted({n.replace("\\", "/") for n in names})
