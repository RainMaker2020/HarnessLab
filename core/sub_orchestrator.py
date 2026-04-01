#!/usr/bin/env python3
"""Sub-Orchestrator — Mini-Harness for a single module sub-workspace.

Owns PLAN.md, harness-scoped history.json, and git isolation under workspace_dir.
Refactored from the former linear Orchestrator (main.py).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from evaluator import (
    BaseEvaluator,
    ContractVerifier,
    EvalResult,
    ExitCodeEvaluator,
    PlaywrightVisualEvaluator,
)
from exceptions import HarnessError
from harness_config import HarnessConfig
from model_router import ModelRouter
from planner import ContractPlanner
from project_mapper import (
    ProjectMapper,
    SituationalContext,
    direct_files_from_task,
    impacted_files,
)
from prompt_generator import PromptGenerator
from sandbox import DockerManager
from trajectory_logger import TrajectoryLogger
from ui import ObservationDeck
from wisdom_rag import WisdomRAG, maybe_wisdom_rag

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_SOS = 2


def _expand_contract_test_command(template: str, task_id: str, workspace: Path) -> str:
    """Substitute placeholders in evaluation.contract_test_command."""
    rel = f"{task_id}.contract.test.ts"
    path = workspace / rel
    return (
        template.replace("{task_id}", task_id)
        .replace("{contract_rel}", rel)
        .replace("{contract_path}", str(path.resolve()))
    )


def _merge_eval_results(a: EvalResult, b: EvalResult) -> EvalResult:
    """Run build/evaluator first; contract tests only if the primary gate passed."""
    cfr = bool(getattr(a, "cross_file_regression", False) or getattr(b, "cross_file_regression", False))
    if not a.passed:
        return EvalResult(passed=False, output=a.output, exit_code=a.exit_code, cross_file_regression=cfr)
    if not b.passed:
        return EvalResult(
            passed=False,
            output=(a.output + "\n--- contract tests ---\n" + b.output).strip(),
            exit_code=b.exit_code if b.exit_code else 1,
            cross_file_regression=cfr,
        )
    return EvalResult(
        passed=True,
        output=(a.output + "\n--- contract tests ---\n" + b.output).strip(),
        exit_code=0,
        cross_file_regression=cfr,
    )


@dataclass
class Task:
    """A single unchecked item from PLAN.md."""

    task_id: str
    description: str
    line_index: int


class PlanParser:
    """Responsibility: Parses workspace/PLAN.md to find and mark off TASK_XX items.

    Provides the Orchestrator with the next pending task and marks it complete
    after a successful commit. Task IDs (TASK_01, TASK_02, …) are deterministic
    keys used in history.json and git commit messages.
    """

    TASK_RE = re.compile(r"^- \[ \] (TASK_\d+): (.+)$")

    def __init__(self, plan_file: Path) -> None:
        """Initialize with path to PLAN.md."""
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


class HistoryManager:
    """Responsibility: Reads and writes history.json — the persistent failure audit log."""

    def __init__(self, history_file: Path) -> None:
        """Initialize, creating the history file if it does not exist."""
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


class GitManager:
    """Responsibility: Performs git operations inside workspace_dir for commit and rollback."""

    def __init__(self, workspace_dir: Path, ui: ObservationDeck) -> None:
        """Initialize with the workspace directory path and an ObservationDeck."""
        self.workspace_dir = workspace_dir
        self.ui = ui

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        """Run a git command inside workspace_dir, raising HarnessError on failure."""
        try:
            return subprocess.run(
                list(args),
                cwd=self.workspace_dir,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise HarnessError(
                "git executable not found. Install git and ensure it is on PATH."
            ) from exc
        except subprocess.SubprocessError as exc:
            raise HarnessError(f"git command failed unexpectedly: {exc}") from exc

    def ensure_repo(self) -> None:
        """Initialize workspace_dir as a git repo if it doesn't already have one."""
        if not (self.workspace_dir / ".git").exists():
            self.workspace_dir.mkdir(parents=True, exist_ok=True)
            self._run("git", "init")
            self._run("git", "config", "user.email", "harness@lab.local")
            self._run("git", "config", "user.name", "HarnessLab")
            (self.workspace_dir / ".gitkeep").touch()
            self._run("git", "add", ".")
            self._run("git", "commit", "-m", "chore: init workspace")
            self.ui.workspace_initialized()

    def current_head(self) -> str:
        """Return the current HEAD commit hash."""
        return self._run("git", "rev-parse", "HEAD").stdout.strip()

    def commit(self, message: str) -> None:
        """Stage all changes and commit with the given message."""
        self._run("git", "add", ".")
        self._run("git", "commit", "-m", message)

    def commit_selected(self, paths: list[Path], message: str) -> None:
        """Stage only the given paths (relative to workspace) and commit."""
        for p in paths:
            rel = p.resolve().relative_to(self.workspace_dir.resolve())
            r = self._run("git", "add", str(rel))
            if r.returncode != 0:
                raise HarnessError(
                    f"git add failed for {rel}: {r.stderr.strip() or r.stdout.strip()}"
                )
        r = self._run("git", "commit", "-m", message)
        if r.returncode != 0:
            raise HarnessError(
                f"git commit failed: {r.stderr.strip() or r.stdout.strip()}"
            )

    def rollback(self) -> None:
        """Discard all uncommitted changes: reset tracked + clean untracked."""
        self._run("git", "reset", "--hard")
        self._run("git", "clean", "-fd")

    def diff_last_commit(self) -> str:
        """Return the unified diff introduced by the most recent commit."""
        count = self._run("git", "rev-list", "--count", "HEAD").stdout.strip()
        if count == "0":
            return ""
        if count == "1":
            r = self._run("git", "show", "--no-color", "HEAD")
            return (r.stdout or "").strip()
        r = self._run("git", "diff", "--no-color", "HEAD~1", "HEAD")
        return (r.stdout or "").strip()

    def list_changed_files_relative(self) -> list[str]:
        """Paths under workspace_dir that differ from HEAD (modified tracked + untracked)."""
        names: list[str] = []
        r = self._run("git", "diff", "--name-only", "HEAD")
        if r.returncode == 0:
            names.extend(line.strip() for line in r.stdout.splitlines() if line.strip())
        r2 = self._run("git", "ls-files", "--others", "--exclude-standard")
        if r2.returncode == 0:
            names.extend(line.strip() for line in r2.stdout.splitlines() if line.strip())
        return sorted({n.replace("\\", "/") for n in names})


class Worker:
    """Responsibility: Executes the claude CLI against the workspace (sub-directory jail)."""

    def __init__(
        self,
        config: HarnessConfig,
        model_router: ModelRouter,
        docker_manager: Optional[DockerManager] = None,
    ) -> None:
        """Initialize with config, a ModelRouter, and an optional DockerManager."""
        self.config = config
        self.model_router = model_router
        self.docker_manager = docker_manager

    def run(self, prompt_file: Path) -> subprocess.CompletedProcess:
        """Dispatch to the correct execution backend based on worker_mode."""
        if self.config.worker_mode == "local":
            return self._run_local(prompt_file)
        elif self.config.worker_mode == "docker":
            return self._run_docker(prompt_file)
        else:
            raise ValueError(f"Unknown worker_mode: '{self.config.worker_mode}'")

    def _run_local(self, prompt_file: Path) -> subprocess.CompletedProcess:
        """Run claude --print <prompt> --model <model> with cwd jailed to workspace_dir."""
        prompt_content = prompt_file.read_text()
        model_args = self.model_router.get_model_args()
        try:
            return subprocess.run(
                ["claude", "--print", prompt_content] + model_args,
                cwd=self.config.workspace_dir,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return subprocess.CompletedProcess(
                args=[], returncode=1, stdout="",
                stderr="[Worker] claude CLI not found. Is it installed and on PATH?",
            )
        except subprocess.SubprocessError as exc:
            return subprocess.CompletedProcess(
                args=[], returncode=1, stdout="",
                stderr=f"[Worker] SubprocessError invoking claude: {exc}",
            )

    def _run_docker(self, prompt_file: Path) -> subprocess.CompletedProcess:
        """Execute claude inside the Docker sandbox via DockerManager."""
        model_args = self.model_router.get_model_args()
        return self.docker_manager.exec_claude(prompt_file, model_args)


class SubOrchestrator:
    """Mini-Harness: PLAN.md task loop scoped to a single sub-workspace directory.

    Success is reported to the caller only when every TASK_* in PLAN.md is complete
    and each task has passed evaluation (no early exit except SOS / circuit breaker).
    """

    def __init__(
        self,
        config: HarnessConfig,
        evaluator: BaseEvaluator,
        ui: ObservationDeck,
    ) -> None:
        """Wire all components. Evaluator is injected for swappability."""
        self.config = config
        self.ui = ui
        if config.distillation_mode and config.distillation_export is None:
            raise HarnessError(
                "paths.distillation_export is required when orchestration.distillation_mode is true."
            )
        self.trajectory_logger: Optional[TrajectoryLogger] = (
            TrajectoryLogger(config.distillation_export) if config.distillation_mode else None
        )
        self._wisdom: Optional[WisdomRAG] = None
        if config.wisdom_rag_enabled:
            try:
                self._wisdom = maybe_wisdom_rag(True, config.resolved_wisdom_store)
                if self._wisdom is not None:
                    self._wisdom.index_from_files(
                        config.history_file,
                        config.distillation_export,
                        config.plan_file,
                    )
            except Exception as exc:
                self.ui.info(f"Wisdom RAG unavailable — continuing without experience recall: {exc}")
                self._wisdom = None
        self.git = GitManager(config.workspace_dir, ui)
        self.history = HistoryManager(config.history_file)
        self.prompt_gen = PromptGenerator(config)
        self.evaluator = evaluator
        self.parser = PlanParser(config.plan_file)
        model_router = ModelRouter(config)
        self.contract_planner: Optional[ContractPlanner] = (
            ContractPlanner(config, model_router) if config.test_first else None
        )
        self.contract_verifier: Optional[ContractVerifier] = (
            ContractVerifier(config) if config.test_first else None
        )
        self._docker_manager = DockerManager(config, ui) if config.worker_mode == "docker" else None
        self.worker = Worker(config, model_router, self._docker_manager)

    def run(self) -> None:
        """Process all unchecked tasks in PLAN.md sequentially."""
        self.git.ensure_repo()
        self.ui.harness_started()

        if self._docker_manager is not None:
            self._docker_manager.start()
        try:
            while True:
                task = self.parser.next_task()
                if task is None:
                    self.ui.all_done()
                    break
                self.ui.task_start(task.task_id, task.description)
                self._run_task(task)
        finally:
            if self._docker_manager is not None:
                self._docker_manager.stop()

    def _negotiate_contract(self, task: Task) -> Path:
        """NEGOTIATE: generate contract tests, verify vs SPEC, lock in git."""
        assert self.contract_planner is not None and self.contract_verifier is not None
        max_n = self.config.contract_negotiation_max_retries
        path: Optional[Path] = None
        for n in range(1, max_n + 1):
            self.ui.contract_round(n, max_n, task.task_id)
            path = self.contract_planner.generate_contract(task.task_id, task.description)
            vr = self.contract_verifier.verify_contract(task.task_id, task.description, path)
            if vr.passed:
                self.ui.contract_approved(task.task_id)
                self.git.commit_selected([path], f"chore: lock contract for {task.task_id}")
                return path
            self.ui.contract_rejected(task.task_id, vr.output)

        self.ui.contract_human_pause(task.task_id)
        input()
        regen = os.environ.get("HARNESS_REGENERATE_CONTRACT_AFTER_PAUSE", "").strip().lower()
        if regen in ("1", "true", "yes"):
            path = self.contract_planner.generate_contract(task.task_id, task.description)
        else:
            path = self.contract_planner.contract_path(task.task_id)
        if not path.exists():
            raise HarnessError(
                f"Expected contract file after human pause: {path}. "
                "Create or restore the contract test file and retry."
            )
        vr = self.contract_verifier.verify_contract(task.task_id, task.description, path)
        if not vr.passed:
            raise HarnessError(
                f"Contract verification failed after human pause.\n{vr.output}"
            )
        self.ui.contract_approved(task.task_id)
        self.git.commit_selected([path], f"chore: lock contract for {task.task_id}")
        return path

    def _run_task(self, task: Task) -> None:
        """Attempt a task up to max_retries times with rollback on failure."""
        wisdom_lessons: list[dict[str, str]] = []
        if self._wisdom is not None:
            try:
                wisdom_lessons = self._wisdom.retrieve_lessons(task.description, top_k=3)
            except Exception as exc:
                self.ui.info(f"Wisdom retrieval skipped: {exc}")
                wisdom_lessons = []

        contract_path: Optional[Path] = None
        if self.config.test_first:
            contract_path = self._negotiate_contract(task)

        for attempt in range(1, self.config.max_retries + 1):
            self.ui.attempt_start(attempt, self.config.max_retries)

            head = self.git.current_head()
            self.ui.baseline(head)

            last_failure = self.history.last_failure(task.task_id)
            project_map = ProjectMapper(self.config.workspace_dir).scan_and_write()
            direct = direct_files_from_task(task.description, self.config.workspace_dir)
            situational = SituationalContext(
                direct_files=direct,
                impacted_files=impacted_files(direct, project_map),
            )
            prompt_file = self.prompt_gen.generate(
                task_id=task.task_id,
                task_description=task.description,
                attempt=attempt,
                last_failure=last_failure,
                contract_path=contract_path,
                situational_context=situational,
                wisdom_lessons=wisdom_lessons,
            )
            self.ui.prompt_written(prompt_file.name)

            self.ui.executing(task.task_id)
            result = self.worker.run(prompt_file)

            if result.returncode == EXIT_SOS:
                self.ui.sos(task.task_id, result.stdout, result.stderr)
                sys.exit(2)

            claude_ok = result.returncode == EXIT_SUCCESS

            edited_paths = self.git.list_changed_files_relative()
            eval_result = self.evaluator.run(edited_paths=edited_paths)
            if self.config.test_first and getattr(self.config, "contract_test_command", None):
                eval_result = _merge_eval_results(
                    eval_result,
                    self._run_contract_tests(task, contract_path),
                )

            if self.config.interactive_mode:
                decision = self.ui.interactive_pause(task.task_id)

                if decision == "commit":
                    self._do_commit(task, tag="[human-approved]", prompt_file=prompt_file)
                    return

                elif decision == "rollback":
                    self._do_failure(task, attempt, result, eval_result, "human rollback")
                    if attempt == self.config.max_retries:
                        self.ui.circuit_breaker(task.task_id, self.config.max_retries)
                        sys.exit(1)
                    continue

                elif decision == "override_done":
                    self.ui.override_resumed()
                    eval_result = self.evaluator.run(
                        edited_paths=self.git.list_changed_files_relative()
                    )
                    if eval_result.passed:
                        self._do_commit(task, tag="[human-override]", prompt_file=prompt_file)
                        return

            if claude_ok and eval_result.passed:
                self._do_commit(task, prompt_file=prompt_file)
                return

            reason = "claude exit non-zero" if not claude_ok else "evaluator failed"
            self._do_failure(task, attempt, result, eval_result, reason)

            if attempt == self.config.max_retries:
                self.ui.circuit_breaker(task.task_id, self.config.max_retries)
                sys.exit(1)

    def _do_commit(self, task: Task, tag: str = "", prompt_file: Optional[Path] = None) -> None:
        """Write changelog, commit to git, optional trajectory log, mark task done in PLAN.md."""
        commit_msg = f"feat: {task.task_id} completed{f' {tag}' if tag else ''}"
        self.prompt_gen.write_changelog(task.task_id, task.description)
        self.git.commit(commit_msg)
        prompt_text = prompt_file.read_text(encoding="utf-8") if prompt_file and prompt_file.exists() else ""
        git_diff = self.git.diff_last_commit()

        def _wisdom_from_record(record: dict) -> None:
            if self._wisdom is None:
                return
            try:
                self._wisdom.ingest_success_trajectory(
                    task.task_id,
                    task.description,
                    str(record.get("input") or ""),
                    str(record.get("output_git_diff") or ""),
                )
            except Exception as exc:
                self.ui.info(f"Wisdom ingest skipped: {exc}")

        if self.trajectory_logger is not None and prompt_file is not None:
            self.trajectory_logger.append(
                task.task_id,
                prompt_text,
                git_diff,
                on_record=_wisdom_from_record if self._wisdom else None,
            )
        elif self._wisdom is not None and prompt_file is not None:
            try:
                self._wisdom.ingest_success_trajectory(
                    task.task_id,
                    task.description,
                    prompt_text,
                    git_diff,
                )
            except Exception as exc:
                self.ui.info(f"Wisdom ingest skipped: {exc}")
        self.parser.mark_done(task)
        self.ui.success(task.task_id)

    def _do_failure(
        self,
        task: Task,
        attempt: int,
        result: subprocess.CompletedProcess,
        eval_result,
        reason: str,
    ) -> None:
        """Record failure to history.json, roll back workspace, and print failure message."""
        self.history.append({
            "task_id": task.task_id,
            "attempt": attempt,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "claude_exit_code": result.returncode,
            "evaluator_passed": eval_result.passed,
            "evaluator_output": eval_result.output,
            "evaluator_cross_file_regression": getattr(
                eval_result, "cross_file_regression", False
            )
            is True,
            "claude_stdout": result.stdout,
            "claude_stderr": result.stderr,
        })
        if self.config.auto_rollback:
            self.git.rollback()
        else:
            self.ui.info("auto_rollback is false — workspace left dirty for inspection.")
        self.ui.failure(attempt, reason)

    def _run_contract_tests(self, task: Task, contract_path: Optional[Path]) -> EvalResult:
        """Optional shell gate: run Vitest/Playwright against the locked contract (test_first)."""
        tpl = getattr(self.config, "contract_test_command", None)
        if not tpl or not str(tpl).strip():
            return EvalResult(passed=True, output="(no evaluation.contract_test_command)", exit_code=0)
        if not contract_path or not contract_path.exists():
            return EvalResult(
                passed=False,
                output="evaluation.contract_test_command is set but the contract file is missing.",
                exit_code=1,
            )
        cmd = _expand_contract_test_command(str(tpl).strip(), task.task_id, self.config.workspace_dir)
        try:
            r = subprocess.run(
                cmd,
                shell=True,
                cwd=self.config.workspace_dir,
                capture_output=True,
                text=True,
                timeout=3600,
            )
        except subprocess.TimeoutExpired:
            return EvalResult(
                passed=False,
                output="Contract test command timed out after 3600s.",
                exit_code=1,
            )
        combined = (r.stdout + r.stderr).strip()
        return EvalResult(
            passed=r.returncode == 0,
            output=combined or "(no output)",
            exit_code=r.returncode,
        )


def build_evaluator(config: HarnessConfig) -> BaseEvaluator:
    """Factory: return the correct BaseEvaluator implementation from harness.yaml config."""
    evaluator_map = {
        "exit_code": ExitCodeEvaluator,
        "playwright": PlaywrightVisualEvaluator,
    }
    cls = evaluator_map.get(config.evaluator_type)
    if cls is None:
        raise HarnessError(
            f"Unknown evaluator type: '{config.evaluator_type}'. "
            f"Valid options: {list(evaluator_map.keys())}"
        )
    return cls(config)
