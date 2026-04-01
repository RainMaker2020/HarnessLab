#!/usr/bin/env python3
"""HarnessLab Orchestrator — manages the AI-driven coding task lifecycle."""

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from rich.console import Console

from prompt_generator import PromptGenerator
from evaluator import Evaluator

console = Console()

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_SOS = 2


@dataclass
class HarnessConfig:
    """Loaded from harness.yaml. Single source of truth for all paths and settings."""

    workspace_dir: Path
    architecture_doc: Path
    spec_doc: Path
    plan_file: Path
    history_file: Path
    build_command: str
    max_retries: int
    claude_model: str
    worker_mode: str

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
            claude_model=raw.get("claude_model", "claude-sonnet-4-6"),
            worker_mode=raw.get("worker_mode", "local"),
        )


@dataclass
class Task:
    """A single unchecked item from PLAN.md."""

    task_id: str
    description: str
    line_index: int


class PlanParser:
    """Parses workspace/PLAN.md for unchecked TASK_XX items."""

    TASK_RE = re.compile(r"^- \[ \] (TASK_\d+): (.+)$")

    def __init__(self, plan_file: Path):
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
    """Reads and writes docs/history.json — the audit log of all task failures."""

    def __init__(self, history_file: Path):
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
    """Performs git operations inside workspace/."""

    def __init__(self, workspace_dir: Path):
        """Initialize with the workspace directory path."""
        self.workspace_dir = workspace_dir

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        """Run a git command inside workspace_dir."""
        return subprocess.run(
            list(args),
            cwd=self.workspace_dir,
            capture_output=True,
            text=True,
        )

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
            console.print("[dim]Initialized workspace git repo.[/dim]")

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
    """Executes the claude CLI against the workspace.

    Supports worker_mode: local (direct subprocess) and docker (future).
    Add new execution backends here by extending _run_<mode>().
    """

    def __init__(self, config: HarnessConfig):
        """Initialize with a HarnessConfig."""
        self.config = config

    def run(self, prompt_file: Path) -> subprocess.CompletedProcess:
        """Dispatch to the correct execution backend based on worker_mode."""
        if self.config.worker_mode == "local":
            return self._run_local(prompt_file)
        elif self.config.worker_mode == "docker":
            return self._run_docker(prompt_file)
        else:
            raise ValueError(f"Unknown worker_mode: '{self.config.worker_mode}'")

    def _run_local(self, prompt_file: Path) -> subprocess.CompletedProcess:
        """Run claude --print <prompt> with cwd jailed to workspace_dir."""
        prompt_content = prompt_file.read_text()
        return subprocess.run(
            ["claude", "--print", prompt_content],
            cwd=self.config.workspace_dir,
            capture_output=True,
            text=True,
        )

    def _run_docker(self, prompt_file: Path) -> subprocess.CompletedProcess:
        """Future: docker exec <container_id> claude --print <prompt>."""
        raise NotImplementedError(
            "Docker worker mode is not yet implemented. "
            "Set worker_mode: local in harness.yaml."
        )


class Orchestrator:
    """Main task loop. Manages lifecycle: generate → execute → evaluate → commit/rollback."""

    def __init__(self, config: HarnessConfig):
        """Wire all components from the shared config."""
        self.config = config
        self.git = GitManager(config.workspace_dir)
        self.history = HistoryManager(config.history_file)
        self.prompt_gen = PromptGenerator(config)
        self.evaluator = Evaluator(config)
        self.parser = PlanParser(config.plan_file)
        self.worker = Worker(config)

    def run(self) -> None:
        """Process all unchecked tasks in PLAN.md sequentially."""
        self.git.ensure_repo()
        console.print("[bold]HarnessLab Orchestrator started.[/bold]")

        while True:
            task = self.parser.next_task()
            if task is None:
                console.print(
                    "\n[bold green]✓ All tasks complete. PLAN.md is fully checked off.[/bold green]"
                )
                break
            console.print(f"\n[bold cyan]━━━ {task.task_id}: {task.description} ━━━[/bold cyan]")
            self._run_task(task)

    def _run_task(self, task: Task) -> None:
        """Attempt a task up to max_retries times with rollback on failure."""
        for attempt in range(1, self.config.max_retries + 1):
            console.print(f"[yellow]  Attempt {attempt}/{self.config.max_retries}[/yellow]")

            # 1. BASELINE
            head = self.git.current_head()
            console.print(f"[dim]  Baseline HEAD: {head[:8]}[/dim]")

            # 2. GENERATE prompt
            last_failure = self.history.last_failure(task.task_id)
            prompt_file = self.prompt_gen.generate(
                task_id=task.task_id,
                task_description=task.description,
                attempt=attempt,
                last_failure=last_failure,
            )
            console.print(f"[dim]  Prompt → {prompt_file.name}[/dim]")

            # 3. EXECUTE
            console.print(f"[blue]  Running claude for {task.task_id}...[/blue]")
            result = self.worker.run(prompt_file)

            # 3a. SOS signal — no rollback, halt immediately
            if result.returncode == EXIT_SOS:
                console.print(
                    f"\n[bold red]🚨 SOS (exit 2): Claude has requested human intervention.[/bold red]\n"
                    f"[red]Task: {task.task_id}\n"
                    f"Stdout:\n{result.stdout}\n"
                    f"Stderr:\n{result.stderr}[/red]\n"
                    f"[bold]No rollback performed. Halting. Review the workspace and restart.[/bold]"
                )
                sys.exit(2)

            claude_ok = result.returncode == EXIT_SUCCESS

            # 4. EVALUATE (pre-commit gatekeeper)
            eval_result = self.evaluator.run()

            # 5a. SUCCESS — both gates pass
            if claude_ok and eval_result.passed:
                self.prompt_gen.write_changelog(task.task_id, task.description)
                self.git.commit(f"feat: {task.task_id} completed")
                self.parser.mark_done(task)
                console.print(f"[bold green]  ✓ {task.task_id} committed.[/bold green]")
                return

            # 5b. FAILURE — rollback, log, retry
            failure_entry = {
                "task_id": task.task_id,
                "attempt": attempt,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "claude_exit_code": result.returncode,
                "evaluator_passed": eval_result.passed,
                "evaluator_output": eval_result.output,
                "claude_stdout": result.stdout,
                "claude_stderr": result.stderr,
            }
            self.history.append(failure_entry)
            self.git.rollback()

            reason = "claude exit non-zero" if not claude_ok else "evaluator failed"
            console.print(f"[red]  ✗ Attempt {attempt} failed ({reason}). Rolled back.[/red]")

            if attempt == self.config.max_retries:
                console.print(
                    f"\n[bold red]CIRCUIT BREAKER TRIPPED: {task.task_id} failed "
                    f"{self.config.max_retries} consecutive times.\n"
                    f"Halting for human intervention. Check docs/history.json for details.[/bold red]"
                )
                sys.exit(1)


def main() -> None:
    """Entry point. Loads harness.yaml from the project root and starts the loop."""
    config_path = Path(__file__).parent.parent / "harness.yaml"
    if not config_path.exists():
        console.print(f"[bold red]Error: harness.yaml not found at {config_path}[/bold red]")
        sys.exit(1)

    config = HarnessConfig.from_yaml(config_path)
    orchestrator = Orchestrator(config)
    orchestrator.run()


if __name__ == "__main__":
    main()
