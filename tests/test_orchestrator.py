import json
import pytest
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from main import Orchestrator, HarnessConfig
from evaluator import ExitCodeEvaluator
from ui import ObservationDeck


@pytest.fixture
def harness_root(tmp_path):
    """Full harness directory structure for integration testing."""
    (tmp_path / "ARCHITECTURE.md").write_text("# Rules\n\nBe correct.")
    (tmp_path / "SPEC.md").write_text("# Spec\n\nBuild it.")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "PLAN.md").write_text(
        "- [ ] TASK_01: Create hello_world.py\n- [ ] TASK_02: Add farewell\n"
    )
    (workspace / ".gitignore").write_text(".harness_prompt.md\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "history.json").write_text("[]")
    return tmp_path


@pytest.fixture
def config(harness_root):
    """Fake config wired to the tmp harness root."""
    workspace = harness_root / "workspace"

    class Cfg:
        workspace_dir = workspace
        architecture_doc = harness_root / "ARCHITECTURE.md"
        spec_doc = harness_root / "SPEC.md"
        plan_file = workspace / "PLAN.md"
        history_file = harness_root / "docs" / "history.json"
        build_command = "echo ok"
        max_retries = 3
        claude_model = "claude-sonnet-4-6"
        worker_mode = "local"
        evaluator_type = "exit_code"

    return Cfg()


def make_orch(config):
    """Build an Orchestrator with injected ExitCodeEvaluator and ObservationDeck."""
    return Orchestrator(config, evaluator=ExitCodeEvaluator(config), ui=ObservationDeck())


def make_proc(returncode=0, stdout="done", stderr=""):
    """Build a mock CompletedProcess."""
    p = MagicMock(spec=subprocess.CompletedProcess)
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


def test_success_commits_and_marks_done(config):
    orch = make_orch(config)
    with patch.object(orch.git, "ensure_repo"), \
         patch.object(orch.git, "current_head", return_value="abc1234"), \
         patch.object(orch.worker, "run", return_value=make_proc(0)), \
         patch.object(orch.evaluator, "run", return_value=MagicMock(passed=True, output="ok", exit_code=0)), \
         patch.object(orch.git, "commit") as mock_commit, \
         patch.object(orch.git, "rollback") as mock_rollback:
        orch.run()

    mock_commit.assert_any_call("feat: TASK_01 completed")
    mock_rollback.assert_not_called()
    assert "- [x] TASK_01" in config.plan_file.read_text()


def test_failure_triggers_rollback_and_logs_history(config):
    orch = make_orch(config)
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
    orch = make_orch(config)
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
    orch = make_orch(config)
    with patch.object(orch.git, "ensure_repo"), \
         patch.object(orch.git, "current_head", return_value="abc1234"), \
         patch.object(orch.worker, "run", return_value=make_proc(2, stdout="I need help")), \
         patch.object(orch.git, "rollback") as mock_rollback, \
         pytest.raises(SystemExit) as exc:
        orch._run_task(orch.parser.next_task())

    assert exc.value.code == 2
    mock_rollback.assert_not_called()


def test_evaluator_failure_triggers_rollback_even_on_claude_success(config):
    orch = make_orch(config)
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
    orch = make_orch(config)
    captured_failures = []

    def capture_generate(task_id, task_description, attempt, last_failure):
        """Record what was passed as last_failure on each call."""
        captured_failures.append(last_failure)
        path = config.workspace_dir / ".harness_prompt.md"
        path.write_text(f"attempt={attempt}")
        return path

    worker_responses = [make_proc(1), make_proc(0)]

    with patch.object(orch.git, "ensure_repo"), \
         patch.object(orch.git, "current_head", return_value="abc1234"), \
         patch.object(orch.prompt_gen, "generate", side_effect=capture_generate), \
         patch.object(orch.prompt_gen, "write_changelog"), \
         patch.object(orch.worker, "run", side_effect=worker_responses), \
         patch.object(orch.evaluator, "run", return_value=MagicMock(passed=True, output="ok", exit_code=0)), \
         patch.object(orch.git, "rollback"), \
         patch.object(orch.git, "commit"):
        orch._run_task(orch.parser.next_task())

    assert captured_failures[0] is None       # first attempt: no prior failure
    assert captured_failures[1] is not None   # retry: failure injected
