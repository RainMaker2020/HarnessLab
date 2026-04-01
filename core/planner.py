"""ContractPlanner — test-first contract generation from SPEC + task (HarnessingLab v1.5)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from exceptions import HarnessError


class ContractPlanner:
    """Generates `workspace/{task_id}.contract.test.ts` using the planner model (claude CLI)."""

    def __init__(self, config, model_router) -> None:
        self._config = config
        self._router = model_router

    def contract_path(self, task_id: str) -> Path:
        return self._config.workspace_dir / f"{task_id}.contract.test.ts"

    def generate_contract(self, task_id: str, task_description: str) -> Path:
        """Write Vitest/Playwright-style tests that encode acceptance criteria for this task."""
        spec_text = self._config.spec_doc.read_text()
        prompt = self._build_planner_prompt(spec_text, task_id, task_description)
        model_args = self._router.get_model_args("planner")
        try:
            result = subprocess.run(
                ["claude", "--print", prompt] + model_args,
                cwd=self._config.workspace_dir,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise HarnessError(
                "claude CLI not found. Install Anthropic Claude Code and ensure `claude` is on PATH."
            ) from exc
        except subprocess.SubprocessError as exc:
            raise HarnessError(f"Contract planner subprocess failed: {exc}") from exc

        if result.returncode != 0:
            raise HarnessError(
                f"Contract planner failed (exit {result.returncode}).\n"
                f"stderr: {result.stderr.strip()}\nstdout: {result.stdout.strip()}"
            )

        body = self._strip_code_fence(result.stdout.strip())
        if not body.strip():
            raise HarnessError("Contract planner produced empty output.")

        out = self.contract_path(task_id)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8")
        return out

    @staticmethod
    def _build_planner_prompt(spec_text: str, task_id: str, task_description: str) -> str:
        return (
            "You are the Contract Planner for an automated harness. "
            "Output ONLY the TypeScript source for a single file — no markdown, no commentary.\n\n"
            "Requirements:\n"
            "- Use Vitest (`import { describe, it, expect } from 'vitest'`) or `@playwright/test` as appropriate.\n"
            "- Every assertion must map to a concrete requirement in SPEC.md for this task.\n"
            "- The file must be self-contained and runnable.\n"
            "- Export nothing; tests only.\n\n"
            f"## Task ID: {task_id}\n"
            f"## Task description:\n{task_description}\n\n"
            "## SPEC.md (full):\n"
            f"{spec_text}\n"
        )

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        """Remove optional ```ts / ``` fences from model output."""
        t = text.strip()
        m = re.match(r"^```(?:typescript|ts|javascript|js)?\s*\n([\s\S]*?)\n```\s*$", t)
        if m:
            return m.group(1).strip()
        return t
