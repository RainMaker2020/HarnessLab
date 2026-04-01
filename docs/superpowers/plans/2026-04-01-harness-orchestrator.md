# HarnessLab Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python orchestrator that manages the full lifecycle of AI-driven coding tasks: parse PLAN.md, generate prompts, execute Claude Code, evaluate output, commit or rollback, and retry with injected error context.

**Architecture:** Control plane (HarnessLab root) owns config and rules; data plane (workspace/) is jailed to Claude Code and git-isolated. PromptGenerator assembles `.harness_prompt.md` per attempt. Worker dispatches to `claude` CLI. Pre-commit gatekeeper requires exit 0 AND evaluator pass before committing.

**Tech Stack:** Python 3.11+, pyyaml, rich, pytest, subprocess, git CLI, claude CLI

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `requirements.txt` | Create | Python dependencies |
| `harness.yaml` | Create | Single source of truth for all paths and config |
| `.gitignore` | Create | Ignore workspace/, __pycache__, .venv |
| `ARCHITECTURE.md` | Create | Human-maintained rules stub (injected into every prompt) |
| `SPEC.md` | Create | Human-maintained spec stub (injected into every prompt) |
| `docs/history.json` | Create | Empty failure log |
| `workspace/PLAN.md` | Create | Sample task list for smoke-testing |
| `workspace/.gitignore` | Create | Ignore .harness_prompt.md |
| `sandbox/Dockerfile` | Create | Claude CLI + Node + Playwright environment |
| `core/evaluator.py` | Create | `Evaluator` — runs build_command, returns `EvalResult` |
| `core/prompt_generator.py` | Create | `PromptGenerator` — assembles `.harness_prompt.md`, writes `CHANGELOG.md` |
| `core/main.py` | Create | `HarnessConfig`, `PlanParser`, `HistoryManager`, `GitManager`, `Worker`, `Orchestrator` |
| `tests/conftest.py` | Create | Shared pytest fixtures (tmp workspace, config) |
| `tests/test_evaluator.py` | Create | Unit tests for Evaluator |
| `tests/test_prompt_generator.py` | Create | Unit tests for PromptGenerator |
| `tests/test_plan_parser.py` | Create | Unit tests for PlanParser |
| `tests/test_history_manager.py` | Create | Unit tests for HistoryManager |
| `tests/test_orchestrator.py` | Create | Integration tests for Orchestrator lifecycle |

---

## Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `harness.yaml`
- Create: `.gitignore`
- Create: `ARCHITECTURE.md`
- Create: `SPEC.md`
- Create: `docs/history.json`
- Create: `workspace/.gitignore`
- Create: `workspace/PLAN.md`

- [ ] **Step 1: Create `requirements.txt`**

```
pyyaml>=6.0
rich>=13.7
pytest>=8.0
pytest-mock>=3.12
```

- [ ] **Step 2: Create `harness.yaml`**

```yaml
workspace_dir: ./workspace
architecture_doc: ./ARCHITECTURE.md
spec_doc: ./SPEC.md
plan_file: ./workspace/PLAN.md
history_file: ./docs/history.json
build_command: "echo 'EVALUATOR_PLACEHOLDER: always passes'"
max_retries: 3
claude_model: claude-sonnet-4-6
worker_mode: local
```

- [ ] **Step 3: Create `.gitignore`**

```gitignore
workspace/
__pycache__/
*.pyc
.venv/
.pytest_cache/
*.egg-info/
dist/
```

- [ ] **Step 4: Create `ARCHITECTURE.md` stub**

```markdown
# HarnessLab Architecture Rules

> This file is injected into every Claude Code prompt. Edit it to enforce project-wide constraints.

## Rules

1. All code must be written inside the `workspace/` directory only.
2. Do not modify any files outside the current task scope.
3. Every function must have a docstring.
4. Follow PEP 8 for Python. Use 4-space indentation.
5. Do not install new packages without listing them in `requirements.txt`.
```

- [ ] **Step 5: Create `SPEC.md` stub**

```markdown
# Project Specification

> This file is injected into every Claude Code prompt. Edit it to describe the project being built.

## Goal

Describe the project goal here.

## Tech Stack

List the technologies here.

## Constraints

- List any technical constraints here.
```

- [ ] **Step 6: Initialize `docs/history.json`**

```json
[]
```

- [ ] **Step 7: Create `workspace/.gitignore`**

```gitignore
.harness_prompt.md
```

- [ ] **Step 8: Create `workspace/PLAN.md` with sample tasks**

```markdown
# Project Plan

- [ ] TASK_01: Create a hello_world.py file that prints "Hello from HarnessLab"
- [ ] TASK_02: Add a farewell() function to hello_world.py that prints "Goodbye from HarnessLab"
```

- [ ] **Step 9: Install dependencies**

Run: `pip install -r requirements.txt`
Expected: All packages install without errors.

- [ ] **Step 10: Commit scaffolding**

```bash
git init
git add requirements.txt harness.yaml .gitignore ARCHITECTURE.md SPEC.md docs/history.json
git commit -m "chore: project scaffolding and config"
```

---

## Task 2: Evaluator Module (TDD)

**Files:**
- Create: `core/__init__.py`
- Create: `core/evaluator.py`
- Create: `tests/__init__.py`
- Create: `tests/test_evaluator.py`

- [ ] **Step 1: Create empty `__init__.py` files**

Create `core/__init__.py` (empty) and `tests/__init__.py` (empty).

- [ ] **Step 2: Write failing tests for `Evaluator`**

Create `tests/test_evaluator.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from evaluator import Evaluator, EvalResult


class FakeConfig:
    build_command = "echo 'ok'"
    workspace_dir = Path("/tmp/workspace")


def test_evalresult_passed_on_exit_zero():
    config = FakeConfig()
    evaluator = Evaluator(config)
    with patch("evaluator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        result = evaluator.run()
    assert result.passed is True
    assert result.exit_code == 0
    assert "ok" in result.output


def test_evalresult_failed_on_nonzero_exit():
    config = FakeConfig()
    evaluator = Evaluator(config)
    with patch("evaluator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="build failed")
        result = evaluator.run()
    assert result.passed is False
    assert result.exit_code == 1
    assert "build failed" in result.output


def test_evalresult_captures_both_stdout_and_stderr():
    config = FakeConfig()
    evaluator = Evaluator(config)
    with patch("evaluator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="compiled\n", stderr="warning: unused var")
        result = evaluator.run()
    assert "compiled" in result.output
    assert "warning" in result.output
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_evaluator.py -v`
Expected: `ModuleNotFoundError: No module named 'evaluator'`

- [ ] **Step 4: Implement `core/evaluator.py`**

```python
"""Evaluator — runs the build_command and reports pass/fail."""

import subprocess
from dataclasses import dataclass


@dataclass
class EvalResult:
    """Result of a single evaluator run."""
    passed: bool
    output: str
    exit_code: int


class Evaluator:
    """Runs the configured build_command against the workspace.

    Currently a placeholder that runs a shell command. Will be extended
    to support Playwright tests when the 'Hater' module is implemented.
    """

    def __init__(self, config):
        self.config = config

    def run(self) -> EvalResult:
        """Run build_command. Returns EvalResult with pass/fail and combined output."""
        result = subprocess.run(
            self.config.build_command,
            shell=True,
            cwd=self.config.workspace_dir,
            capture_output=True,
            text=True,
        )
        combined_output = (result.stdout + result.stderr).strip()
        return EvalResult(
            passed=result.returncode == 0,
            output=combined_output,
            exit_code=result.returncode,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_evaluator.py -v`
Expected:
```
tests/test_evaluator.py::test_evalresult_passed_on_exit_zero PASSED
tests/test_evaluator.py::test_evalresult_failed_on_nonzero_exit PASSED
tests/test_evaluator.py::test_evalresult_captures_both_stdout_and_stderr PASSED
3 passed
```

- [ ] **Step 6: Commit**

```bash
git add core/__init__.py core/evaluator.py tests/__init__.py tests/test_evaluator.py
git commit -m "feat: add Evaluator module with tests"
```

---

## Task 3: PromptGenerator Module (TDD)

**Files:**
- Create: `core/prompt_generator.py`
- Create: `tests/test_prompt_generator.py`

- [ ] **Step 1: Write failing tests for `PromptGenerator`**

Create `tests/test_prompt_generator.py`:

```python
import pytest
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from prompt_generator import PromptGenerator


@pytest.fixture
def tmp_harness(tmp_path):
    """Create a minimal harness directory structure in tmp_path."""
    arch = tmp_path / "ARCHITECTURE.md"
    arch.write_text("# Architecture Rules\n\nRule 1: Be correct.")
    spec = tmp_path / "SPEC.md"
    spec.write_text("# Spec\n\nBuild something useful.")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    history = tmp_path / "docs" / "history.json"
    history.parent.mkdir()
    history.write_text("[]")

    class FakeConfig:
        architecture_doc = arch
        spec_doc = spec
        workspace_dir = workspace
        history_file = history

    return tmp_path, FakeConfig()


def test_generate_writes_harness_prompt_md(tmp_harness):
    _, config = tmp_harness
    gen = PromptGenerator(config)
    path = gen.generate("TASK_01", "Create hello_world.py", attempt=1, last_failure=None)
    assert path == config.workspace_dir / ".harness_prompt.md"
    assert path.exists()


def test_generate_contains_architecture_rules(tmp_harness):
    _, config = tmp_harness
    gen = PromptGenerator(config)
    gen.generate("TASK_01", "Create hello_world.py", attempt=1, last_failure=None)
    content = (config.workspace_dir / ".harness_prompt.md").read_text()
    assert "Architecture Rules" in content
    assert "Rule 1: Be correct." in content


def test_generate_contains_spec(tmp_harness):
    _, config = tmp_harness
    gen = PromptGenerator(config)
    gen.generate("TASK_01", "Create hello_world.py", attempt=1, last_failure=None)
    content = (config.workspace_dir / ".harness_prompt.md").read_text()
    assert "Build something useful." in content


def test_generate_contains_task_id_and_description(tmp_harness):
    _, config = tmp_harness
    gen = PromptGenerator(config)
    gen.generate("TASK_01", "Create hello_world.py", attempt=1, last_failure=None)
    content = (config.workspace_dir / ".harness_prompt.md").read_text()
    assert "TASK_01" in content
    assert "Create hello_world.py" in content


def test_generate_injects_last_failure_on_retry(tmp_harness):
    _, config = tmp_harness
    gen = PromptGenerator(config)
    failure = {
        "task_id": "TASK_01",
        "attempt": 1,
        "claude_exit_code": 1,
        "evaluator_passed": False,
        "evaluator_output": "SyntaxError: invalid syntax",
        "claude_stdout": "",
        "claude_stderr": "Error: bad code",
    }
    gen.generate("TASK_01", "Create hello_world.py", attempt=2, last_failure=failure)
    content = (config.workspace_dir / ".harness_prompt.md").read_text()
    assert "SyntaxError: invalid syntax" in content
    assert "Error: bad code" in content


def test_generate_no_retry_section_on_first_attempt(tmp_harness):
    _, config = tmp_harness
    gen = PromptGenerator(config)
    gen.generate("TASK_01", "Create hello_world.py", attempt=1, last_failure=None)
    content = (config.workspace_dir / ".harness_prompt.md").read_text()
    assert "PREVIOUS FAILURE" not in content


def test_write_changelog_creates_file(tmp_harness):
    _, config = tmp_harness
    gen = PromptGenerator(config)
    gen.write_changelog("TASK_01", "Create hello_world.py")
    changelog = config.workspace_dir / "CHANGELOG.md"
    assert changelog.exists()
    content = changelog.read_text()
    assert "TASK_01" in content
    assert "Create hello_world.py" in content


def test_write_changelog_appends_on_multiple_tasks(tmp_harness):
    _, config = tmp_harness
    gen = PromptGenerator(config)
    gen.write_changelog("TASK_01", "First task")
    gen.write_changelog("TASK_02", "Second task")
    content = (config.workspace_dir / "CHANGELOG.md").read_text()
    assert "TASK_01" in content
    assert "TASK_02" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_prompt_generator.py -v`
Expected: `ModuleNotFoundError: No module named 'prompt_generator'`

- [ ] **Step 3: Implement `core/prompt_generator.py`**

```python
"""PromptGenerator — assembles .harness_prompt.md for each task attempt."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class PromptGenerator:
    """Reads ARCHITECTURE.md, SPEC.md, and failure history to write .harness_prompt.md.

    Called before every claude invocation. On success, also writes to CHANGELOG.md.
    """

    def __init__(self, config):
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

        prompt_path = self.config.workspace_dir / ".harness_prompt.md"
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_prompt_generator.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/prompt_generator.py tests/test_prompt_generator.py
git commit -m "feat: add PromptGenerator module with tests"
```

---

## Task 4: PlanParser and HistoryManager (TDD)

**Files:**
- Create: `tests/test_plan_parser.py`
- Create: `tests/test_history_manager.py`
- Note: Both classes will be implemented inside `core/main.py` in Task 5. Tests are written first.

- [ ] **Step 1: Write failing tests for `PlanParser`**

Create `tests/test_plan_parser.py`:

```python
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from main import PlanParser, Task


@pytest.fixture
def plan_file(tmp_path):
    p = tmp_path / "PLAN.md"
    p.write_text(
        "# Plan\n\n"
        "- [ ] TASK_01: Create hello_world.py\n"
        "- [ ] TASK_02: Add farewell() function\n"
        "- [x] TASK_00: Already done\n"
    )
    return p


def test_next_task_returns_first_unchecked(plan_file):
    parser = PlanParser(plan_file)
    task = parser.next_task()
    assert task is not None
    assert task.task_id == "TASK_01"
    assert task.description == "Create hello_world.py"


def test_next_task_skips_checked_tasks(tmp_path):
    p = tmp_path / "PLAN.md"
    p.write_text("- [x] TASK_01: Done\n- [ ] TASK_02: Not done\n")
    parser = PlanParser(p)
    task = parser.next_task()
    assert task.task_id == "TASK_02"


def test_next_task_returns_none_when_all_done(tmp_path):
    p = tmp_path / "PLAN.md"
    p.write_text("- [x] TASK_01: Done\n- [x] TASK_02: Also done\n")
    parser = PlanParser(p)
    assert parser.next_task() is None


def test_mark_done_checks_off_task(plan_file):
    parser = PlanParser(plan_file)
    task = parser.next_task()
    parser.mark_done(task)
    content = plan_file.read_text()
    assert "- [x] TASK_01" in content
    assert "- [ ] TASK_02" in content


def test_task_id_format_is_deterministic(plan_file):
    parser = PlanParser(plan_file)
    task = parser.next_task()
    assert task.task_id == "TASK_01"
```

- [ ] **Step 2: Write failing tests for `HistoryManager`**

Create `tests/test_history_manager.py`:

```python
import pytest
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from main import HistoryManager


@pytest.fixture
def history_file(tmp_path):
    f = tmp_path / "docs" / "history.json"
    f.parent.mkdir()
    f.write_text("[]")
    return f


def test_append_adds_entry(history_file):
    mgr = HistoryManager(history_file)
    mgr.append({"task_id": "TASK_01", "attempt": 1, "claude_exit_code": 1})
    data = json.loads(history_file.read_text())
    assert len(data) == 1
    assert data[0]["task_id"] == "TASK_01"


def test_append_accumulates_entries(history_file):
    mgr = HistoryManager(history_file)
    mgr.append({"task_id": "TASK_01", "attempt": 1})
    mgr.append({"task_id": "TASK_01", "attempt": 2})
    data = json.loads(history_file.read_text())
    assert len(data) == 2


def test_last_failure_returns_most_recent_for_task(history_file):
    mgr = HistoryManager(history_file)
    mgr.append({"task_id": "TASK_01", "attempt": 1, "claude_exit_code": 1})
    mgr.append({"task_id": "TASK_01", "attempt": 2, "claude_exit_code": 1})
    last = mgr.last_failure("TASK_01")
    assert last["attempt"] == 2


def test_last_failure_returns_none_for_unknown_task(history_file):
    mgr = HistoryManager(history_file)
    assert mgr.last_failure("TASK_99") is None


def test_last_failure_only_matches_correct_task(history_file):
    mgr = HistoryManager(history_file)
    mgr.append({"task_id": "TASK_01", "attempt": 1})
    mgr.append({"task_id": "TASK_02", "attempt": 1})
    last = mgr.last_failure("TASK_02")
    assert last["task_id"] == "TASK_02"


def test_history_manager_creates_file_if_missing(tmp_path):
    f = tmp_path / "docs" / "history.json"
    mgr = HistoryManager(f)
    assert f.exists()
    assert json.loads(f.read_text()) == []
```

- [ ] **Step 3: Run both test files to verify they fail**

Run: `pytest tests/test_plan_parser.py tests/test_history_manager.py -v`
Expected: `ImportError` — `PlanParser` and `HistoryManager` not yet defined.

---

## Task 5: Core Orchestrator — `main.py`

**Files:**
- Create: `core/main.py`

- [ ] **Step 1: Implement `core/main.py`**

```python
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
                console.print("\n[bold green]✓ All tasks complete. PLAN.md is fully checked off.[/bold green]")
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

            # 2. GENERATE
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
```

- [ ] **Step 2: Run PlanParser and HistoryManager tests**

Run: `pytest tests/test_plan_parser.py tests/test_history_manager.py -v`
Expected: All 11 tests PASS.

- [ ] **Step 3: Run full test suite**

Run: `pytest -v`
Expected: All tests pass. Zero failures.

- [ ] **Step 4: Commit**

```bash
git add core/main.py
git commit -m "feat: add Orchestrator, PlanParser, HistoryManager, GitManager, Worker"
```

---

## Task 6: Orchestrator Integration Tests (TDD)

**Files:**
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: Write integration tests for the Orchestrator lifecycle**

Create `tests/test_orchestrator.py`:

```python
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from main import Orchestrator, HarnessConfig


@pytest.fixture
def harness_root(tmp_path):
    """Full harness directory structure for integration testing."""
    arch = tmp_path / "ARCHITECTURE.md"
    arch.write_text("# Rules\n\nBe correct.")
    spec = tmp_path / "SPEC.md"
    spec.write_text("# Spec\n\nBuild it.")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan = workspace / "PLAN.md"
    plan.write_text("- [ ] TASK_01: Create hello_world.py\n- [ ] TASK_02: Add farewell\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    history = docs / "history.json"
    history.write_text("[]")
    workspace_gitignore = workspace / ".gitignore"
    workspace_gitignore.write_text(".harness_prompt.md\n")
    return tmp_path


@pytest.fixture
def config(harness_root):
    workspace = harness_root / "workspace"
    docs = harness_root / "docs"

    class Cfg:
        workspace_dir = workspace
        architecture_doc = harness_root / "ARCHITECTURE.md"
        spec_doc = harness_root / "SPEC.md"
        plan_file = workspace / "PLAN.md"
        history_file = docs / "history.json"
        build_command = "echo ok"
        max_retries = 3
        claude_model = "claude-sonnet-4-6"
        worker_mode = "local"

    return Cfg()


def make_proc(returncode=0, stdout="done", stderr=""):
    p = MagicMock(spec=subprocess.CompletedProcess)
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


def test_success_commits_and_marks_done(config):
    orch = Orchestrator(config)
    with patch.object(orch.git, "ensure_repo"), \
         patch.object(orch.git, "current_head", return_value="abc1234"), \
         patch.object(orch.worker, "run", return_value=make_proc(0)), \
         patch.object(orch.evaluator, "run", return_value=MagicMock(passed=True, output="ok", exit_code=0)), \
         patch.object(orch.git, "commit") as mock_commit, \
         patch.object(orch.git, "rollback") as mock_rollback:
        orch.run()

    mock_commit.assert_called_once_with("feat: TASK_01 completed")
    mock_rollback.assert_not_called()
    assert "- [x] TASK_01" in config.plan_file.read_text()


def test_failure_triggers_rollback_and_logs_history(config):
    orch = Orchestrator(config)
    with patch.object(orch.git, "ensure_repo"), \
         patch.object(orch.git, "current_head", return_value="abc1234"), \
         patch.object(orch.worker, "run", return_value=make_proc(1, stderr="syntax error")), \
         patch.object(orch.evaluator, "run", return_value=MagicMock(passed=False, output="fail", exit_code=1)), \
         patch.object(orch.git, "commit") as mock_commit, \
         patch.object(orch.git, "rollback") as mock_rollback, \
         pytest.raises(SystemExit):
        orch._run_task(orch.parser.next_task())

    mock_rollback.assert_called()
    mock_commit.assert_not_called()
    history = json.loads(config.history_file.read_text())
    assert len(history) > 0
    assert history[0]["task_id"] == "TASK_01"
    assert history[0]["claude_exit_code"] == 1


def test_circuit_breaker_halts_after_max_retries(config):
    orch = Orchestrator(config)
    with patch.object(orch.git, "ensure_repo"), \
         patch.object(orch.git, "current_head", return_value="abc1234"), \
         patch.object(orch.worker, "run", return_value=make_proc(1)), \
         patch.object(orch.evaluator, "run", return_value=MagicMock(passed=False, output="fail", exit_code=1)), \
         patch.object(orch.git, "rollback"), \
         pytest.raises(SystemExit) as exc:
        orch._run_task(orch.parser.next_task())

    assert exc.value.code == 1
    history = json.loads(config.history_file.read_text())
    assert len(history) == config.max_retries


def test_sos_exit_code_halts_without_rollback(config):
    orch = Orchestrator(config)
    with patch.object(orch.git, "ensure_repo"), \
         patch.object(orch.git, "current_head", return_value="abc1234"), \
         patch.object(orch.worker, "run", return_value=make_proc(2, stdout="I need help")), \
         patch.object(orch.git, "rollback") as mock_rollback, \
         pytest.raises(SystemExit) as exc:
        orch._run_task(orch.parser.next_task())

    assert exc.value.code == 2
    mock_rollback.assert_not_called()


def test_evaluator_failure_triggers_rollback_even_on_claude_success(config):
    orch = Orchestrator(config)
    with patch.object(orch.git, "ensure_repo"), \
         patch.object(orch.git, "current_head", return_value="abc1234"), \
         patch.object(orch.worker, "run", return_value=make_proc(0)), \
         patch.object(orch.evaluator, "run", return_value=MagicMock(passed=False, output="test failed", exit_code=1)), \
         patch.object(orch.git, "commit") as mock_commit, \
         patch.object(orch.git, "rollback") as mock_rollback, \
         pytest.raises(SystemExit):
        orch._run_task(orch.parser.next_task())

    mock_commit.assert_not_called()
    mock_rollback.assert_called()


def test_retry_injects_last_failure_into_prompt(config):
    orch = Orchestrator(config)
    generated_prompts = []

    def capture_generate(*args, **kwargs):
        path = config.workspace_dir / ".harness_prompt.md"
        path.write_text(f"attempt={kwargs.get('attempt', args[2])}")
        generated_prompts.append(kwargs.get("last_failure"))
        return path

    responses = [make_proc(1), make_proc(0)]

    with patch.object(orch.git, "ensure_repo"), \
         patch.object(orch.git, "current_head", return_value="abc1234"), \
         patch.object(orch.prompt_gen, "generate", side_effect=capture_generate), \
         patch.object(orch.prompt_gen, "write_changelog"), \
         patch.object(orch.worker, "run", side_effect=responses), \
         patch.object(orch.evaluator, "run", return_value=MagicMock(passed=True, output="ok", exit_code=0)), \
         patch.object(orch.git, "rollback"), \
         patch.object(orch.git, "commit"):
        orch._run_task(orch.parser.next_task())

    assert generated_prompts[0] is None       # first attempt: no prior failure
    assert generated_prompts[1] is not None   # retry: failure injected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -v`
Expected: Most tests fail — `Orchestrator` not yet fully wired.

- [ ] **Step 3: Run full test suite**

Run: `pytest -v`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_orchestrator.py tests/test_plan_parser.py tests/test_history_manager.py
git commit -m "test: add integration tests for full Orchestrator lifecycle"
```

---

## Task 7: Sandbox Dockerfile

**Files:**
- Create: `sandbox/Dockerfile`

- [ ] **Step 1: Create `sandbox/Dockerfile`**

```dockerfile
FROM node:20-slim

# Install Python, git, and system deps for Playwright
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    wget \
    ca-certificates \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Install Claude CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Install Playwright and browsers
RUN npm install -g playwright && playwright install chromium --with-deps

# Set up Python venv
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy and install harness Python deps
WORKDIR /harness
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy harness control plane (workspace/ is mounted at runtime)
COPY harness.yaml .
COPY ARCHITECTURE.md .
COPY SPEC.md .
COPY core/ core/
COPY docs/ docs/

# workspace/ is mounted as a volume at runtime:
#   docker run -v $(pwd)/workspace:/harness/workspace harnesslab
VOLUME ["/harness/workspace"]

CMD ["python3", "core/main.py"]
```

- [ ] **Step 2: Commit**

```bash
git add sandbox/Dockerfile
git commit -m "feat: add sandbox Dockerfile with Claude CLI and Playwright"
```

---

## Task 8: Final Wiring and Smoke Test

**Files:**
- Modify: `workspace/PLAN.md` (verify sample tasks are in place)
- Verify: `docs/history.json` is `[]`

- [ ] **Step 1: Run full test suite one final time**

Run: `pytest -v --tb=short`
Expected: All tests pass. Zero failures, zero errors.

- [ ] **Step 2: Verify project structure**

Run:
```bash
find . -not -path './workspace/*' -not -path './.git/*' -not -path './__pycache__/*' \
       -not -path './.venv/*' -not -path './tests/__pycache__/*' -not -path './core/__pycache__/*' \
       -type f | sort
```

Expected output (order may vary):
```
./ARCHITECTURE.md
./SPEC.md
./.gitignore
./harness.yaml
./requirements.txt
./core/__init__.py
./core/evaluator.py
./core/main.py
./core/prompt_generator.py
./docs/history.json
./docs/superpowers/plans/2026-04-01-harness-orchestrator.md
./docs/superpowers/specs/2026-04-01-orchestrator-design.md
./sandbox/Dockerfile
./tests/__init__.py
./tests/test_evaluator.py
./tests/test_history_manager.py
./tests/test_orchestrator.py
./tests/test_plan_parser.py
./tests/test_prompt_generator.py
```

- [ ] **Step 3: Verify harness can be imported without error**

Run: `cd core && python3 -c "import main; print('Import OK')" && cd ..`
Expected: `Import OK`

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "chore: finalize HarnessLab orchestrator — ready for TASK_01"
```
