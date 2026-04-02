"""ProgressTracker — writes workspace/PROGRESS.md after every successful commit.

This is the Handoff Artifact: a fresh WorkerSession reads it on startup so the
model orients itself without scanning git history.

Pattern: follows core/wisdom_rag.py — accepts HarnessConfig, no global state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from exceptions import HarnessError
from harness_config import HarnessConfig


@dataclass
class ProgressSnapshot:
    completed_tasks: list[str]
    file_tree: list[str]
    architectural_notes: str
    last_updated: str


class ProgressTracker:
    """Writes workspace/PROGRESS.md after every successful commit."""

    FILE_NAME = "PROGRESS.md"

    def __init__(self, config: HarnessConfig, ui) -> None:
        self.config = config
        self.ui = ui
        self.path = config.workspace_dir / self.FILE_NAME

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def update(
        self,
        completed_tasks: list[str],
        architectural_notes: str = "",
    ) -> None:
        """Render and write PROGRESS.md. Raises HarnessError on I/O failure."""
        try:
            file_tree = self._scan_workspace()
            snapshot = ProgressSnapshot(
                completed_tasks=completed_tasks,
                file_tree=file_tree,
                architectural_notes=architectural_notes,
                last_updated=datetime.now(timezone.utc).isoformat(),
            )
            self.path.write_text(self._render(snapshot), encoding="utf-8")
            self.ui.info(f"[ProgressTracker] Written → {self.path}")
        except OSError as exc:
            raise HarnessError(f"ProgressTracker write failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read(self) -> str:
        """Return raw markdown content, or empty string if file does not exist."""
        if self.path.exists():
            return self.path.read_text(encoding="utf-8")
        return ""

    def exists(self) -> bool:
        return self.path.exists()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scan_workspace(self) -> list[str]:
        workspace = self.config.workspace_dir
        excludes = {".git", "node_modules", "__pycache__", ".harness_prompt.md"}
        return sorted(
            str(p.relative_to(workspace))
            for p in workspace.rglob("*")
            if p.is_file() and not any(ex in p.parts for ex in excludes)
        )

    @staticmethod
    def _render(snap: ProgressSnapshot) -> str:
        tasks_block = "\n".join(f"- [x] {t}" for t in snap.completed_tasks) or "_none yet_"
        tree_block = "\n".join(f"  {f}" for f in snap.file_tree) or "_empty_"
        notes_block = snap.architectural_notes.strip() or "_none_"

        return (
            f"# HarnessLab — Workspace Progress\n"
            f"<!-- AUTO-GENERATED — do not edit by hand -->\n"
            f"Last updated: {snap.last_updated}\n"
            f"\n"
            f"## Completed tasks\n"
            f"{tasks_block}\n"
            f"\n"
            f"## Current file tree\n"
            f"```\n"
            f"{tree_block}\n"
            f"```\n"
            f"\n"
            f"## Architectural notes\n"
            f"{notes_block}\n"
        )
