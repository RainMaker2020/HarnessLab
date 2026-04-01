"""PromptGenerator — assembles .harness_prompt.md for each task attempt."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class PromptGenerator:
    """Reads ARCHITECTURE.md, SPEC.md, and failure history to write .harness_prompt.md.

    Called before every claude invocation. On success, also writes to CHANGELOG.md.
    """

    def __init__(self, config):
        """Initialize with a config object exposing architecture_doc, spec_doc, workspace_dir."""
        self.config = config

    def generate(
        self,
        task_id: str,
        task_description: str,
        attempt: int,
        last_failure: Optional[dict],
    ) -> Path:
        """Write workspace/.harness_prompt.md. Returns the path to the file."""
        architecture = self.config.architecture_doc.read_text()
        spec = self.config.spec_doc.read_text()

        sections = [
            "# HarnessLab — Autonomous Task Prompt",
            f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
            f"**Task:** {task_id} (Attempt {attempt})",
            "",
            "---",
            "",
            "## Architecture Rules",
            "",
            architecture,
            "",
            "---",
            "",
            "## Project Specification",
            "",
            spec,
            "",
            "---",
            "",
            "## Your Task",
            "",
            f"**Task ID:** `{task_id}`",
            f"**Description:** {task_description}",
            "",
            "Complete this task fully. All changes must be made inside the current working directory.",
            "Do not modify files outside the scope of this task.",
        ]

        if last_failure is not None:
            sections += [
                "",
                "---",
                "",
                "## ⚠️ PREVIOUS FAILURE — Learn From This",
                "",
                f"Your previous attempt (attempt {last_failure['attempt']}) failed.",
                f"Claude exit code: `{last_failure['claude_exit_code']}`",
                f"Evaluator passed: `{last_failure['evaluator_passed']}`",
                "",
                "**Evaluator output:**",
                "```",
                last_failure.get("evaluator_output", "(none)"),
                "```",
                "",
                "**Claude stderr:**",
                "```",
                last_failure.get("claude_stderr", "(none)"),
                "```",
                "",
                "Diagnose the root cause before writing any code. Do not repeat the same mistake.",
            ]

        prompt_path = getattr(self.config, "prompt_buffer_path", None) or (
            self.config.workspace_dir / ".harness_prompt.md"
        )
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text("\n".join(sections))
        return prompt_path

    def write_changelog(self, task_id: str, task_description: str) -> None:
        """Append a success entry to workspace/CHANGELOG.md."""
        changelog = self.config.workspace_dir / "CHANGELOG.md"
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        entry = f"\n## {task_id} — {timestamp}\n\n- {task_description}\n"
        if changelog.exists():
            changelog.write_text(changelog.read_text() + entry)
        else:
            changelog.write_text(f"# Changelog\n{entry}")
