import json
import pytest
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from exceptions import HarnessError
from main import Orchestrator
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
        models = {
            "planner": "claude-3-7-sonnet",
            "generator": "claude-3-5-haiku",
            "evaluator": "claude-3-5-sonnet-20241022",
        }
        worker_mode = "local"
        evaluator_type = "exit_code"
        interactive_mode = False  # off by default; individual tests override
        playwright_target = "index.html"
        vision_rubric = "Test rubric"
        auto_rollback = True
        distillation_mode = False
        distillation_export = None
        prompt_buffer_path = workspace / ".harness_prompt.md"
        project = SimpleNamespace(name="test-harness")

    return Cfg()


def make_orch(config):
    """Build an Orchestrator with injected ExitCodeEvaluator and ObservationDeck."""
    return Orchestrator(
        config,
        evaluator=ExitCodeEvaluator(config),
        ui=ObservationDeck(),
    )


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


# ─── Interactive Pause — ObservationDeck.interactive_pause() ──────────────────

def test_interactive_pause_returns_commit_on_c():
    from ui import ObservationDeck
    ui = ObservationDeck()
    with patch("builtins.input", return_value="c"):
        decision = ui.interactive_pause("TASK_01")
    assert decision == "commit"


def test_interactive_pause_returns_rollback_on_r():
    from ui import ObservationDeck
    ui = ObservationDeck()
    with patch("builtins.input", return_value="r"):
        decision = ui.interactive_pause("TASK_01")
    assert decision == "rollback"


def test_interactive_pause_override_waits_for_enter_then_returns_override_done():
    from ui import ObservationDeck
    ui = ObservationDeck()
    # First input() = 'o' (menu choice), second input() = '' (Enter after editing)
    with patch("builtins.input", side_effect=["o", ""]):
        decision = ui.interactive_pause("TASK_01")
    assert decision == "override_done"


def test_interactive_pause_loops_on_invalid_input():
    from ui import ObservationDeck
    ui = ObservationDeck()
    # 'x' is invalid, then 'c' is valid
    with patch("builtins.input", side_effect=["x", "c"]):
        decision = ui.interactive_pause("TASK_01")
    assert decision == "commit"


# ─── Interactive Pause — Orchestrator lifecycle integration ───────────────────

def test_interactive_commit_force_commits_even_when_evaluator_fails(config):
    """Human choosing (c) must commit even if the evaluator returned failure."""
    config.interactive_mode = True
    orch = make_orch(config)

    with patch.object(orch.git, "ensure_repo"), \
         patch.object(orch.git, "current_head", return_value="abc1234"), \
         patch.object(orch.worker, "run", return_value=make_proc(0)), \
         patch.object(orch.evaluator, "run", return_value=MagicMock(passed=False, output="fail", exit_code=1)), \
         patch.object(orch.git, "commit") as mock_commit, \
         patch.object(orch.git, "rollback") as mock_rollback, \
         patch.object(orch.ui, "interactive_pause", return_value="commit"):
        orch._run_task(orch.parser.next_task())

    mock_commit.assert_called_once()
    assert "[human-approved]" in mock_commit.call_args[0][0]
    mock_rollback.assert_not_called()


def test_interactive_rollback_triggers_failure_path(config):
    """Human choosing (r) must roll back even if claude and evaluator both passed."""
    config.interactive_mode = True
    config.max_retries = 1  # one attempt so circuit breaker fires → SystemExit
    orch = make_orch(config)

    with patch.object(orch.git, "ensure_repo"), \
         patch.object(orch.git, "current_head", return_value="abc1234"), \
         patch.object(orch.worker, "run", return_value=make_proc(0)), \
         patch.object(orch.evaluator, "run", return_value=MagicMock(passed=True, output="ok", exit_code=0)), \
         patch.object(orch.git, "commit") as mock_commit, \
         patch.object(orch.git, "rollback") as mock_rollback, \
         patch.object(orch.ui, "interactive_pause", return_value="rollback"), \
         pytest.raises(SystemExit):
        orch._run_task(orch.parser.next_task())

    mock_rollback.assert_called_once()
    mock_commit.assert_not_called()


def test_interactive_override_reruns_evaluator_and_commits_on_pass(config):
    """Human choosing (o) must re-run the evaluator; if re-eval passes, commit."""
    config.interactive_mode = True
    orch = make_orch(config)

    # First eval fails, override re-eval passes
    eval_responses = [
        MagicMock(passed=False, output="fail", exit_code=1),
        MagicMock(passed=True,  output="ok",   exit_code=0),
    ]

    with patch.object(orch.git, "ensure_repo"), \
         patch.object(orch.git, "current_head", return_value="abc1234"), \
         patch.object(orch.worker, "run", return_value=make_proc(0)), \
         patch.object(orch.evaluator, "run", side_effect=eval_responses), \
         patch.object(orch.git, "commit") as mock_commit, \
         patch.object(orch.git, "rollback") as mock_rollback, \
         patch.object(orch.ui, "interactive_pause", return_value="override_done"):
        orch._run_task(orch.parser.next_task())

    mock_commit.assert_called_once()
    assert "[human-override]" in mock_commit.call_args[0][0]
    mock_rollback.assert_not_called()


def test_interactive_override_falls_through_to_failure_when_reeval_fails(config):
    """If override re-eval still fails and claude was also non-zero, roll back."""
    config.interactive_mode = True
    config.max_retries = 1
    orch = make_orch(config)

    # Both evals fail
    eval_fail = MagicMock(passed=False, output="still broken", exit_code=1)

    with patch.object(orch.git, "ensure_repo"), \
         patch.object(orch.git, "current_head", return_value="abc1234"), \
         patch.object(orch.worker, "run", return_value=make_proc(1)), \
         patch.object(orch.evaluator, "run", return_value=eval_fail), \
         patch.object(orch.git, "rollback") as mock_rollback, \
         patch.object(orch.ui, "interactive_pause", return_value="override_done"), \
         pytest.raises(SystemExit) as exc:
        orch._run_task(orch.parser.next_task())

    assert exc.value.code == 1
    mock_rollback.assert_called()


def test_distillation_requires_export_path(config):
    """orchestration.distillation_mode without paths.distillation_export must fail fast."""
    config.distillation_mode = True
    config.distillation_export = None
    with pytest.raises(HarnessError, match="distillation_export"):
        make_orch(config)


def test_distillation_appends_jsonl(config, harness_root):
    """Successful commit with distillation logs prompt + git diff to JSONL."""
    export = harness_root / "docs" / "traj.jsonl"
    config.distillation_mode = True
    config.distillation_export = export
    orch = make_orch(config)
    task = orch.parser.next_task()
    prompt_file = config.workspace_dir / ".harness_prompt.md"
    prompt_file.write_text("PROMPT BODY")
    with patch.object(orch.git, "commit"), \
         patch.object(orch.prompt_gen, "write_changelog"), \
         patch.object(orch.git, "diff_last_commit", return_value="diff --git a/x\n"), \
         patch.object(orch.parser, "mark_done"), \
         patch.object(orch.ui, "success"):
        orch._do_commit(task, prompt_file=prompt_file)

    line = export.read_text().strip().splitlines()[0]
    data = json.loads(line)
    assert data["input"] == "PROMPT BODY"
    assert "diff --git" in data["output_git_diff"]
    assert data["task_id"] == "TASK_01"


def test_auto_rollback_false_skips_git_reset(config):
    """When auto_rollback is false, failure path must not call git rollback."""
    config.auto_rollback = False
    orch = make_orch(config)
    with patch.object(orch.git, "ensure_repo"), \
         patch.object(orch.git, "current_head", return_value="abc1234"), \
         patch.object(orch.worker, "run", return_value=make_proc(1)), \
         patch.object(orch.evaluator, "run", return_value=MagicMock(passed=False, output="fail", exit_code=1)), \
         patch.object(orch.git, "commit") as mock_commit, \
         patch.object(orch.git, "rollback") as mock_rollback, \
         pytest.raises(SystemExit):
        orch._run_task(orch.parser.next_task())

    mock_rollback.assert_not_called()
    mock_commit.assert_not_called()
