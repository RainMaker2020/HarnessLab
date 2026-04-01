#!/usr/bin/env python3
"""HarnessLab Orchestrator — lightweight entry point for the AI coding task lifecycle.

Pipeline: PLAN.md → PromptGenerator → Worker (claude CLI) → BaseEvaluator → git commit/rollback.
All sub-concerns live in their own modules:
  ui.py           — ObservationDeck (all terminal output)
  model_router.py — ModelRouter (dynamic model selection from harness.yaml)
  docker_manager.py — DockerManager (sandbox container lifecycle)
  evaluator.py    — BaseEvaluator + concrete implementations
  prompt_generator.py — PromptGenerator (prompt assembly)
"""

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from docker_manager import DockerManager, HarnessError
from evaluator import BaseEvaluator, ExitCodeEvaluator, PlaywrightVisualEvaluator
from model_router import ModelRouter
from prompt_generator import PromptGenerator
from ui import ObservationDeck

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_SOS = 2


@dataclass
class HarnessConfig:
    """Responsibility: Loaded from harness.yaml; single source of truth for all paths and settings.

    Every component receives a HarnessConfig rather than raw strings, ensuring that
    harness.yaml is the only file a human needs to edit to change runtime behaviour.
    """

    workspace_dir: Path
    architecture_doc: Path
    spec_doc: Path
    plan_file: Path
    history_file: Path
    build_command: str
    max_retries: int
    models: dict
    worker_mode: str
    evaluator_type: str
    interactive_mode: bool
    playwright_target: str

    @classmethod
    def from_yaml(cls, path: Path) -> "HarnessConfig":
        """Parse harness.yaml relative to its own directory."""
        raw = yaml.safe_load(path.read_text())
        base = path.parent
        return cls(
            workspace_dir=(base / raw["workspace_dir"]).resolve(),
            architecture_doc=(base / raw["architecture_doc"]).resolve(),
            spec_doc=(base / raw["spec_doc"]).resolve(),
            plan_file=(base / raw["plan_file"]).resolve(),
            history_file=(base / raw["history_file"]).resolve(),
            build_command=raw["build_command"],
            max_retries=raw.get("max_retries", 3),
            models=raw.get("models") or {
                "planner": raw.get("claude_model", "claude-sonnet-4-6"),
                "generator": raw.get("claude_model", "claude-sonnet-4-6"),
                "evaluator": raw.get("vision_model", "claude-3-5-sonnet-20241022"),
            },
            worker_mode=raw.get("worker_mode", "local"),
            evaluator_type=raw.get("evaluator", "exit_code"),
            interactive_mode=raw.get("interactive_mode", False),
            playwright_target=raw.get("playwright_target", "index.html"),
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
    """Responsibility: Reads and writes docs/history.json — the persistent failure audit log.

    On failure, appends a structured entry. On retry, supplies the last failure entry
    to PromptGenerator so Claude can learn from prior mistakes within the same task.
    """

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
    """Responsibility: Performs git operations inside workspace/ for commit and rollback.

    After claude succeeds and the evaluator passes, GitManager commits the change.
    On failure, it performs a hard reset + clean to restore the workspace to the
    last known good state before the next retry attempt.
    """

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
        """Initialize workspace/ as a git repo if it doesn't already have one."""
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

    def rollback(self) -> None:
        """Discard all uncommitted changes: reset tracked + clean untracked."""
        self._run("git", "reset", "--hard")
        self._run("git", "clean", "-fd")


class Worker:
    """Responsibility: Executes the claude CLI against the workspace.

    Delegates model selection to ModelRouter (no hardcoded model strings) and Docker
    execution to DockerManager. Wraps all subprocess calls in try/except so claude
    not being installed or a docker exec failure returns a graceful failure result
    rather than crashing the orchestrator.
    """

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


class Orchestrator:
    """Responsibility: Coordinates the full task lifecycle loop.

    Sequences: baseline → prompt generation → execution → evaluation → commit/rollback.
    Owns the retry counter and circuit breaker. Delegates all output to ObservationDeck,
    all model selection to ModelRouter, all git operations to GitManager, and all
    evaluation to the injected BaseEvaluator implementation.
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
        self.git = GitManager(config.workspace_dir, ui)
        self.history = HistoryManager(config.history_file)
        self.prompt_gen = PromptGenerator(config)
        self.evaluator = evaluator
        self.parser = PlanParser(config.plan_file)
        model_router = ModelRouter(config)
        docker_manager = DockerManager(config, ui) if config.worker_mode == "docker" else None
        self.worker = Worker(config, model_router, docker_manager)

    def run(self) -> None:
        """Process all unchecked tasks in PLAN.md sequentially."""
        self.git.ensure_repo()
        self.ui.harness_started()

        while True:
            task = self.parser.next_task()
            if task is None:
                self.ui.all_done()
                break
            self.ui.task_start(task.task_id, task.description)
            self._run_task(task)

    def _run_task(self, task: Task) -> None:
        """Attempt a task up to max_retries times with rollback on failure."""
        for attempt in range(1, self.config.max_retries + 1):
            self.ui.attempt_start(attempt, self.config.max_retries)

            # 1. BASELINE
            head = self.git.current_head()
            self.ui.baseline(head)

            # 2. GENERATE prompt
            last_failure = self.history.last_failure(task.task_id)
            prompt_file = self.prompt_gen.generate(
                task_id=task.task_id,
                task_description=task.description,
                attempt=attempt,
                last_failure=last_failure,
            )
            self.ui.prompt_written(prompt_file.name)

            # 3. EXECUTE
            self.ui.executing(task.task_id)
            result = self.worker.run(prompt_file)

            # 3a. SOS signal — no rollback, halt immediately
            if result.returncode == EXIT_SOS:
                self.ui.sos(task.task_id, result.stdout, result.stderr)
                sys.exit(2)

            claude_ok = result.returncode == EXIT_SUCCESS

            # 4. EVALUATE (pre-commit gatekeeper)
            eval_result = self.evaluator.run()

            # 4.5. INTERACTIVE PAUSE — human reviews evaluation before commit/rollback
            if self.config.interactive_mode:
                decision = self.ui.interactive_pause(task.task_id)

                if decision == "commit":
                    # Human approves — force commit regardless of evaluator
                    self._do_commit(task, tag="[human-approved]")
                    return

                elif decision == "rollback":
                    # Human rejects — force rollback and continue retry loop
                    self._do_failure(task, attempt, result, eval_result, "human rollback")
                    if attempt == self.config.max_retries:
                        self.ui.circuit_breaker(task.task_id, self.config.max_retries)
                        sys.exit(1)
                    continue

                elif decision == "override_done":
                    # Human edited workspace/ — re-run evaluator on the updated files
                    self.ui.override_resumed()
                    eval_result = self.evaluator.run()
                    if eval_result.passed:
                        # Re-evaluation passed — commit the human's manual fix
                        self._do_commit(task, tag="[human-override]")
                        return
                    # Re-evaluation still failed — fall through to normal failure path

            # 5a. SUCCESS — both gates pass (or override re-eval failed, fall to 5b)
            if claude_ok and eval_result.passed:
                self._do_commit(task)
                return

            # 5b. FAILURE — rollback, log, retry
            reason = "claude exit non-zero" if not claude_ok else "evaluator failed"
            self._do_failure(task, attempt, result, eval_result, reason)

            if attempt == self.config.max_retries:
                self.ui.circuit_breaker(task.task_id, self.config.max_retries)
                sys.exit(1)

    def _do_commit(self, task: Task, tag: str = "") -> None:
        """Write changelog, commit to git, and mark the task done in PLAN.md."""
        commit_msg = f"feat: {task.task_id} completed{f' {tag}' if tag else ''}"
        self.prompt_gen.write_changelog(task.task_id, task.description)
        self.git.commit(commit_msg)
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
            "claude_stdout": result.stdout,
            "claude_stderr": result.stderr,
        })
        self.git.rollback()
        self.ui.failure(attempt, reason)


def _build_evaluator(config: HarnessConfig) -> BaseEvaluator:
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


def main() -> None:
    """Entry point. Loads harness.yaml, wires dependencies, and starts the loop."""
    config_path = Path(__file__).parent.parent / "harness.yaml"
    ui = ObservationDeck()

    if not config_path.exists():
        ui.fatal_error(f"harness.yaml not found at {config_path}")
        sys.exit(1)

    try:
        config = HarnessConfig.from_yaml(config_path)
        evaluator = _build_evaluator(config)
        orchestrator = Orchestrator(config, evaluator=evaluator, ui=ui)
        orchestrator.run()
    except HarnessError as exc:
        ui.fatal_error(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
