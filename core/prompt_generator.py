"""PromptGenerator — assembles .harness_prompt.md for each task attempt."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from project_mapper import (
    PROJECT_MAP_LINE_THRESHOLD,
    dependency_pruning,
    dumps_project_map_deterministic,
)

if TYPE_CHECKING:
    from project_mapper import SituationalContext


def _dependency_graph_markdown(
    task_id: str,
    task_description: str,
    workspace_dir: Path,
    plan_file: Optional[Path],
) -> list[str]:
    """Full or pruned ``.project_map.json`` for situational awareness (threshold: line count)."""
    map_path = workspace_dir / ".project_map.json"
    if not map_path.is_file() or plan_file is None:
        return []

    try:
        raw_text = map_path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except (OSError, json.JSONDecodeError):
        return []

    line_count = len(raw_text.splitlines())
    if line_count <= PROJECT_MAP_LINE_THRESHOLD:
        header = (
            f"Dependency graph — **full map** (`.project_map.json` has {line_count} lines, "
            f"≤ {PROJECT_MAP_LINE_THRESHOLD} line threshold)."
        )
        payload = dumps_project_map_deterministic(data)
    else:
        header = (
            "--- Situational Context (Pruned: Global map size exceeds threshold) ---\n\n"
            f"`.project_map.json` has **{line_count}** lines (threshold {PROJECT_MAP_LINE_THRESHOLD}). "
            "Only the **immediate neighborhood** of this task’s files is shown (imports + dependents)."
        )
        pruned = dependency_pruning(
            task_id,
            plan_file=plan_file,
            workspace=workspace_dir,
            project_map=data,
            fallback_description=task_description,
        )
        payload = dumps_project_map_deterministic(pruned)

    return [
        "",
        "### Structured dependency data (JSON)",
        "",
        header,
        "",
        "```json",
        payload,
        "```",
    ]


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
        contract_path: Optional[Path] = None,
        situational_context: Optional["SituationalContext"] = None,
    ) -> Path:
        """Write workspace/.harness_prompt.md. Returns the path to the file."""
        architecture = self.config.architecture_doc.read_text()
        spec = self.config.spec_doc.read_text()

        global_interface_block: list[str] = []
        gi_path = getattr(self.config, "global_interface_doc", None)
        if gi_path is not None and Path(gi_path).exists():
            gi_body = Path(gi_path).read_text(encoding="utf-8").strip()
            if gi_body:
                global_interface_block = [
                    "",
                    "---",
                    "",
                    "## Global Interface Contract (cross-module)",
                    "",
                    "Other modules will call into this area only through this contract. "
                    "Implement code that satisfies these signatures and behaviors.",
                    "",
                    gi_body,
                ]

        situational_block: list[str] = []
        if situational_context is not None:
            direct = situational_context.direct_files
            impacted = situational_context.impacted_files
            primary = situational_context.primary_file
            plan_file = getattr(self.config, "plan_file", None)
            graph_md = _dependency_graph_markdown(
                task_id,
                task_description,
                Path(self.config.workspace_dir),
                Path(plan_file) if plan_file is not None else None,
            )
            situational_block = [
                "",
                "---",
                "",
                "## Situational Awareness (Level 4)",
                "",
                f"You are editing **{primary}** as the primary focus for this task.",
                "",
                "**Directly related files** (parsed from task description):",
                *(
                    [f"- `{p}`" for p in direct]
                    if direct
                    else ["- *(none — add explicit paths in the task text for tighter mapping)*"]
                ),
                "",
                "**Downstream impact:** the following files depend on imports from your direct files. "
                "If you change a **public export or signature** in a direct file, you **MUST** update these "
                "consumers in the **same sprint** so the application architecture stays consistent:",
                *(
                    [f"- `{p}`" for p in impacted]
                    if impacted
                    else ["- *(none in project graph — see `.project_map.json`)*"]
                ),
                "",
                "The project graph is regenerated each task as `workspace/.project_map.json`.",
                *graph_md,
                "",
            ]

        sections = [
            "# HarnessingLab v1.5 — Autonomous Task Prompt",
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
            *situational_block,
            *global_interface_block,
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

        if contract_path is not None and contract_path.exists():
            contract_body = contract_path.read_text(encoding="utf-8")
            sections += [
                "",
                "---",
                "",
                "## The CONTRACT (immutable)",
                "",
                "The following tests are your CONTRACT. You are successful ONLY when these tests pass.",
                "You are NOT allowed to modify any `*.contract.test.ts` files or the contract file for this task.",
                "",
                "```typescript",
                contract_body,
                "```",
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
            if last_failure.get("evaluator_cross_file_regression"):
                sections += [
                    "",
                    "**Note:** The previous failure was flagged as a **cross-file regression** "
                    "(error in a file you did not edit). Fix the root cause in your edits and update dependents.",
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
