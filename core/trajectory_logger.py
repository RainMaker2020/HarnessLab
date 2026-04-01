"""TrajectoryLogger — append successful prompt + git diff to JSONL for distillation."""

import json
from datetime import datetime, timezone
from pathlib import Path


class TrajectoryLogger:
    """Writes one JSON object per line: input (prompt text) and output (git diff)."""

    def __init__(self, export_path: Path) -> None:
        self._path = export_path

    def append(self, task_id: str, prompt_text: str, git_diff: str) -> None:
        """Append a trajectory record to the JSONL export file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "task_id": task_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "input": prompt_text,
            "output_git_diff": git_diff,
        }
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
