#!/usr/bin/env python3
"""PLAN.md parsing and harness history — shared by tools and tests (no orchestrator loop)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Task:
    """A single unchecked item from PLAN.md."""

    task_id: str
    description: str
    line_index: int


class PlanParser:
    """Parses workspace PLAN.md to find and mark off TASK_XX items."""

    TASK_RE = re.compile(r"^- \[ \] (TASK_\d+): (.+)$")

    def __init__(self, plan_file: Path) -> None:
        self.plan_file = plan_file

    def next_task(self) -> Optional[Task]:
        """Return the first unchecked task, or None if all are done."""
        lines = self.plan_file.read_text().splitlines()
        for i, line in enumerate(lines):
            m = self.TASK_RE.match(line.strip())
            if m:
                return Task(task_id=m.group(1), description=m.group(2), line_index=i)
        return None

    def mark_done(self, task: Task) -> None:
        """Replace `- [ ]` with `- [x]` for the given task."""
        lines = self.plan_file.read_text().splitlines()
        lines[task.line_index] = lines[task.line_index].replace("- [ ]", "- [x]", 1)
        self.plan_file.write_text("\n".join(lines) + "\n")

    DONE_RE = re.compile(r"^- \[x\] (TASK_\d+): (.+)$")

    def completed_tasks(self) -> list[str]:
        """Return list of 'TASK_XX: description' strings for all checked-off tasks."""
        lines = self.plan_file.read_text().splitlines()
        return [
            f"{m.group(1)}: {m.group(2)}"
            for line in lines
            for m in [self.DONE_RE.match(line.strip())]
            if m
        ]


class HistoryManager:
    """Reads and writes history.json — the persistent failure audit log."""

    def __init__(self, history_file: Path) -> None:
        self.history_file = history_file
        if not self.history_file.exists():
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            self.history_file.write_text("[]")

    def append(self, entry: dict) -> None:
        """Append a failure entry to history.json."""
        history = json.loads(self.history_file.read_text())
        history.append(entry)
        self.history_file.write_text(json.dumps(history, indent=2))

    def last_failure(self, task_id: str) -> Optional[dict]:
        """Return the most recent failure for a given task_id, or None."""
        history = json.loads(self.history_file.read_text())
        matches = [e for e in history if e.get("task_id") == task_id]
        return matches[-1] if matches else None
