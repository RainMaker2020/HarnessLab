"""Scaffolder — Level 0: turn a vague idea into HarnessLab specifications via the planner model."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, TextIO

from harness.exceptions import HarnessError

SCAFFOLDER_SYSTEM_PROMPT = (
    "You are the Senior Architect for HarnessLab. Your goal is to translate a vague human idea "
    'into a set of rigid, AI-executable specifications. You know that the "Worker" is an AI '
    '(Claude 3.5 Haiku) and the "Evaluator" is a ruthless "Hater" (Claude 3.7). Write specifications '
    "that are clear, atomic, and testable. Prevent AI-slop by mandating custom UI and strict typography."
)

_BEGIN_ARCH = "---BEGIN_ARCHITECTURE_MD---"
_END_ARCH = "---END_ARCHITECTURE_MD---"
_BEGIN_SPEC = "---BEGIN_SPEC_MD---"
_END_SPEC = "---END_SPEC_MD---"
_BEGIN_PLAN = "---BEGIN_PLAN_MD---"
_END_PLAN = "---END_PLAN_MD---"


class Scaffolder:
    """Generates ARCHITECTURE.md, SPEC.md, and workspace/PLAN.md using ``models.planner`` (Claude CLI)."""

    def __init__(self, config, model_router) -> None:
        self._config = config
        self._router = model_router

    def existing_spec_conflicts(self) -> list[Path]:
        """Paths under ``architecture_doc`` / ``spec_doc`` that already exist and would be overwritten."""
        out: list[Path] = []
        for p in (self._config.architecture_doc, self._config.spec_doc):
            if p.exists() and p.is_file():
                out.append(p)
        return out

    def run(
        self,
        user_prompt: str,
        *,
        force: bool = False,
        stdin: Optional[TextIO] = None,
    ) -> None:
        """Generate specs. If ``force`` is False and ARCHITECTURE.md/SPEC.md exist, prompt via ``stdin``."""
        if not (user_prompt or "").strip():
            raise HarnessError("Scaffolder: user_prompt must be a non-empty string.")

        input_stream = stdin if stdin is not None else sys.stdin

        conflicts = self.existing_spec_conflicts()
        if conflicts and not force:
            lines = "\n".join(f"  - {p}" for p in conflicts)
            msg = (
                "The following file(s) already exist and would be overwritten:\n"
                f"{lines}\n"
                "Type 'yes' to overwrite, or anything else to abort: "
            )
            print(msg, end="", flush=True)
            reply = input_stream.readline()
            if (reply or "").strip().lower() != "yes":
                raise HarnessError("Scaffolder aborted: existing ARCHITECTURE.md or SPEC.md not overwritten.")

        full_prompt = self._build_user_prompt(user_prompt.strip())
        raw = self._invoke_planner(full_prompt)
        arch_body, spec_body, plan_body = self._parse_triple_output(raw)

        self._write_file(self._config.architecture_doc, arch_body)
        self._write_file(self._config.spec_doc, spec_body)
        self._write_file(self._config.plan_file, plan_body)

    @staticmethod
    def _write_file(path: Path, body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body.strip() + "\n", encoding="utf-8")

    def _invoke_planner(self, prompt: str) -> str:
        model_args = self._router.get_model_args("planner")
        timeout = int(getattr(self._config, "planner_timeout_seconds", None) or 900)
        repo_root = Path(__file__).resolve().parent.parent
        try:
            result = subprocess.run(
                ["claude", "--print", prompt] + model_args,
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise HarnessError(
                f"Scaffolder timed out after {timeout}s. "
                "Increase evaluation.planner_timeout_seconds in harness.yaml if needed."
            ) from exc
        except FileNotFoundError as exc:
            raise HarnessError(
                "claude CLI not found. Install Anthropic Claude Code and ensure `claude` is on PATH."
            ) from exc
        except subprocess.SubprocessError as exc:
            raise HarnessError(f"Scaffolder subprocess failed: {exc}") from exc

        if result.returncode != 0:
            raise HarnessError(
                f"Scaffolder failed (exit {result.returncode}).\n"
                f"stderr: {result.stderr.strip()}\nstdout: {result.stdout.strip()}"
            )

        out = (result.stdout or "").strip()
        if not out:
            raise HarnessError("Scaffolder produced empty output.")
        return out

    @staticmethod
    def _build_user_prompt(user_idea: str) -> str:
        return (
            f"System instruction (follow strictly):\n\n{SCAFFOLDER_SYSTEM_PROMPT}\n\n"
            "---\n\n"
            "Human idea to scaffold:\n"
            f"{user_idea}\n\n"
            "You must output EXACTLY three parts using these delimiters. "
            "Do not add any text before the first delimiter or after the last. "
            "Do not wrap sections in markdown code fences.\n\n"
            f"{_BEGIN_ARCH}\n"
            "(Full markdown body for ARCHITECTURE.md: strict tech stack, state management rules, "
            "and explicit constraints for the Evaluator / 'Hater'.)\n"
            f"{_END_ARCH}\n\n"
            f"{_BEGIN_SPEC}\n"
            "(Full markdown body for SPEC.md: feature list, aesthetic requirements, and functional goals.)\n"
            f"{_END_SPEC}\n\n"
            f"{_BEGIN_PLAN}\n"
            "(Full markdown body for workspace/PLAN.md: a deterministic task list. "
            "Each line must match: `- [ ] TASK_NN: short description` with NN zero-padded, starting at 01.)\n"
            f"{_END_PLAN}\n"
        )

    @staticmethod
    def _parse_triple_output(text: str) -> tuple[str, str, str]:
        def extract(start: str, end: str, label: str) -> str:
            m = re.search(
                re.escape(start) + r"\s*([\s\S]*?)\s*" + re.escape(end),
                text,
                re.MULTILINE,
            )
            if not m:
                raise HarnessError(
                    f"Scaffolder output missing or malformed {label} block "
                    f"(expected delimiters {start!r} … {end!r})."
                )
            return m.group(1).strip()

        arch = extract(_BEGIN_ARCH, _END_ARCH, "ARCHITECTURE")
        spec = extract(_BEGIN_SPEC, _END_SPEC, "SPEC")
        plan = extract(_BEGIN_PLAN, _END_PLAN, "PLAN")
        return arch, spec, plan
