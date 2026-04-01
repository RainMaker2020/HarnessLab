"""WorkerSession — persistent Anthropic SDK conversation replacing the subprocess claude CLI call.

One WorkerSession lives for the entire SubOrchestrator.run() loop. The messages
list is the conversation history — the model remembers everything it built in
previous tasks within the same plan.

Pattern: follows core/wisdom_rag.py — accepts HarnessConfig, no global state.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import anthropic

from exceptions import HarnessError
from harness_config import HarnessConfig
from progress_tracker import ProgressTracker

_COMPACTION_CHAR_LIMIT = 600_000   # ~150k tokens at 4 chars/token
_RECENT_MESSAGES_KEPT = 10        # messages preserved verbatim after compaction


class WorkerSession:
    """Persistent SDK session replacing the subprocess Worker."""

    def __init__(
        self,
        config: HarnessConfig,
        progress_tracker: ProgressTracker,
        ui,
    ) -> None:
        self.config = config
        self.tracker = progress_tracker
        self.ui = ui
        self.client = anthropic.Anthropic()
        self.model: str = config.models.get("generator", "claude-sonnet-4-6")
        self.messages: list[dict] = []
        self._total_input_tokens = 0
        self._total_output_tokens = 0

        self._bootstrap()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_task(self, prompt: str) -> str:
        """Feed the next task prompt into the persistent session. Returns full response text."""
        self._maybe_compact()
        self.messages.append({"role": "user", "content": prompt})

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8096,
                system=self._system_prompt(),
                messages=self.messages,
            )
        except anthropic.APIError as exc:
            raise HarnessError(f"WorkerSession API call failed: {exc}") from exc

        assistant_text = response.content[0].text
        self.messages.append({"role": "assistant", "content": assistant_text})

        self._total_input_tokens += response.usage.input_tokens
        self._total_output_tokens += response.usage.output_tokens
        self.ui.info(
            f"[WorkerSession] tokens — in: {response.usage.input_tokens:,} "
            f"out: {response.usage.output_tokens:,} "
            f"(session total: {self._total_input_tokens + self._total_output_tokens:,})"
        )
        return assistant_text

    @property
    def session_cost_tokens(self) -> dict:
        return {
            "input": self._total_input_tokens,
            "output": self._total_output_tokens,
            "total": self._total_input_tokens + self._total_output_tokens,
        }

    # ------------------------------------------------------------------
    # Bootstrap — resume or fresh start
    # ------------------------------------------------------------------

    def _bootstrap(self) -> None:
        progress = self.tracker.read()
        if progress:
            self.ui.info("[WorkerSession] Resuming from PROGRESS.md")
            self.messages = [
                {
                    "role": "user",
                    "content": (
                        "Resume context — the workspace already has work in progress.\n\n"
                        f"{progress}\n\n"
                        "Use this to orient yourself. Do not redo completed tasks. "
                        "Continue from where we left off."
                    ),
                },
                {
                    "role": "assistant",
                    "content": (
                        "Understood. I have read the workspace progress. "
                        "I can see the completed tasks and the current file tree. "
                        "I will continue from the next pending task."
                    ),
                },
            ]
        else:
            self.ui.info("[WorkerSession] Fresh session — no PROGRESS.md found")
            self.messages = []

    # ------------------------------------------------------------------
    # Compaction
    # ------------------------------------------------------------------

    def _maybe_compact(self) -> None:
        total_chars = sum(len(str(m.get("content", ""))) for m in self.messages)
        if total_chars > _COMPACTION_CHAR_LIMIT:
            self.ui.info(
                f"[WorkerSession] Compacting — history is {total_chars:,} chars "
                f"(limit {_COMPACTION_CHAR_LIMIT:,})"
            )
            self._compact()

    def _compact(self) -> None:
        old_messages = self.messages[:-_RECENT_MESSAGES_KEPT]
        recent = self.messages[-_RECENT_MESSAGES_KEPT:]

        if not old_messages:
            return

        summary = self._summarize_messages(old_messages)
        self.messages = [
            {
                "role": "user",
                "content": (
                    "[Compacted session context]\n"
                    "The following is a summary of earlier conversation turns "
                    "that have been compacted to save context space:\n\n"
                    f"{summary}"
                ),
            },
            {
                "role": "assistant",
                "content": "Understood. I have the session summary and will continue.",
            },
            *recent,
        ]
        self.ui.info(
            f"[WorkerSession] Compacted {len(old_messages)} messages → 1 summary block. "
            f"Kept {len(recent)} recent messages verbatim."
        )

    def _summarize_messages(self, messages: list[dict]) -> str:
        """Use the planner model to summarize old turns for context compaction."""
        flat = "\n\n".join(
            f"[{m['role'].upper()}]\n{m['content']}" for m in messages
        )
        prompt = (
            "You are summarizing a coding session for context compaction. "
            "Produce a dense technical summary covering:\n"
            "1. Which files were created or modified and their purpose\n"
            "2. Key architectural decisions made\n"
            "3. Any bugs discovered and how they were fixed\n"
            "4. The current state of the workspace\n\n"
            "Be precise. A future coding agent will use this to continue the work.\n\n"
            f"SESSION TURNS TO SUMMARIZE:\n{flat}"
        )
        try:
            response = self.client.messages.create(
                model=self.config.models.get("planner", "claude-sonnet-4-6"),
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except anthropic.APIError as exc:
            self.ui.info(f"[WorkerSession] Compaction summarization failed: {exc}. Keeping raw history.")
            return flat[:4000] + "\n...[truncated]"

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def _system_prompt(self) -> str:
        arch_path = self.config.architecture_doc
        spec_path = self.config.spec_doc

        arch = arch_path.read_text(encoding="utf-8") if arch_path.exists() else ""
        spec = spec_path.read_text(encoding="utf-8") if spec_path.exists() else ""

        return (
            f"You are a senior software engineer working autonomously in "
            f"`{self.config.workspace_dir}`. "
            "You implement tasks one at a time. You never declare a task done "
            "unless all specified tests pass. You never recreate files that already exist "
            "unless the task explicitly requires modification.\n\n"
            f"ARCHITECTURE CONSTRAINTS:\n{arch}\n\n"
            f"PRODUCT SPECIFICATION:\n{spec}"
        )
