"""Unit tests for WorkerSession — mocks Anthropic client; no real API calls (TDD RED phase)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(arch_path: Path, spec_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.models = {"generator": "claude-sonnet-4-6", "planner": "claude-sonnet-4-6"}
    cfg.architecture_doc = arch_path
    cfg.spec_doc = spec_path
    cfg.workspace_dir = arch_path.parent
    return cfg


def _make_tracker(content: str = "") -> MagicMock:
    tracker = MagicMock()
    tracker.read.return_value = content
    return tracker


def _make_response(text: str, input_tokens: int = 100, output_tokens: int = 50) -> MagicMock:
    resp = MagicMock()
    resp.content = [MagicMock(text=text)]
    resp.usage.input_tokens = input_tokens
    resp.usage.output_tokens = output_tokens
    return resp


class MockAPIError(Exception):
    """Stand-in for anthropic.APIError in tests."""


# ---------------------------------------------------------------------------
# Bootstrap behaviour
# ---------------------------------------------------------------------------

class TestBootstrap:
    def test_empty_messages_when_no_progress(self, tmp_path: Path) -> None:
        with patch("worker_session.anthropic.Anthropic"):
            from worker_session import WorkerSession
            session = WorkerSession(
                _make_config(tmp_path / "ARCH.md", tmp_path / "SPEC.md"),
                _make_tracker(""),
                MagicMock(),
            )
        assert session.messages == []

    def test_seeds_context_from_progress_md(self, tmp_path: Path) -> None:
        progress = "# HarnessLab\n## Completed tasks\n- [x] TASK_01: Done"
        with patch("worker_session.anthropic.Anthropic"):
            from worker_session import WorkerSession
            session = WorkerSession(
                _make_config(tmp_path / "ARCH.md", tmp_path / "SPEC.md"),
                _make_tracker(progress),
                MagicMock(),
            )
        assert len(session.messages) == 2
        assert session.messages[0]["role"] == "user"
        assert "TASK_01" in session.messages[0]["content"]
        assert session.messages[1]["role"] == "assistant"


# ---------------------------------------------------------------------------
# run_task()
# ---------------------------------------------------------------------------

class TestRunTask:
    def test_appends_user_and_assistant_messages(self, tmp_path: Path) -> None:
        with patch("worker_session.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = _make_response("Done!")
            from worker_session import WorkerSession
            session = WorkerSession(
                _make_config(tmp_path / "ARCH.md", tmp_path / "SPEC.md"),
                _make_tracker(),
                MagicMock(),
            )
            result = session.run_task("Implement TASK_01")

        assert result == "Done!"
        assert len(session.messages) == 2
        assert session.messages[0] == {"role": "user", "content": "Implement TASK_01"}
        assert session.messages[1] == {"role": "assistant", "content": "Done!"}

    def test_accumulates_token_counts_across_calls(self, tmp_path: Path) -> None:
        with patch("worker_session.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.side_effect = [
                _make_response("First", input_tokens=100, output_tokens=50),
                _make_response("Second", input_tokens=200, output_tokens=75),
            ]
            from worker_session import WorkerSession
            session = WorkerSession(
                _make_config(tmp_path / "ARCH.md", tmp_path / "SPEC.md"),
                _make_tracker(),
                MagicMock(),
            )
            session.run_task("Task 1")
            session.run_task("Task 2")

        tokens = session.session_cost_tokens
        assert tokens["input"] == 300
        assert tokens["output"] == 125
        assert tokens["total"] == 425

    def test_raises_harness_error_on_api_failure(self, tmp_path: Path) -> None:
        from exceptions import HarnessError
        with patch("worker_session.anthropic.Anthropic") as MockClient, \
             patch("worker_session.anthropic.APIError", MockAPIError):
            MockClient.return_value.messages.create.side_effect = MockAPIError("rate limit")
            from worker_session import WorkerSession
            session = WorkerSession(
                _make_config(tmp_path / "ARCH.md", tmp_path / "SPEC.md"),
                _make_tracker(),
                MagicMock(),
            )
            with pytest.raises(HarnessError, match="WorkerSession API call failed"):
                session.run_task("Task")

    def test_passes_system_prompt_to_api(self, tmp_path: Path) -> None:
        arch = tmp_path / "ARCH.md"
        arch.write_text("Hexagonal arch.")
        spec = tmp_path / "SPEC.md"
        spec.write_text("CLI tool.")
        with patch("worker_session.anthropic.Anthropic") as MockClient:
            mock_create = MockClient.return_value.messages.create
            mock_create.return_value = _make_response("ok")
            from worker_session import WorkerSession
            session = WorkerSession(_make_config(arch, spec), _make_tracker(), MagicMock())
            session.run_task("do something")
            call_kwargs = mock_create.call_args
        assert "system" in call_kwargs.kwargs or (call_kwargs.args and len(call_kwargs.args) > 1)


# ---------------------------------------------------------------------------
# session_cost_tokens property
# ---------------------------------------------------------------------------

class TestSessionCostTokens:
    def test_zero_before_any_call(self, tmp_path: Path) -> None:
        with patch("worker_session.anthropic.Anthropic"):
            from worker_session import WorkerSession
            session = WorkerSession(
                _make_config(tmp_path / "ARCH.md", tmp_path / "SPEC.md"),
                _make_tracker(),
                MagicMock(),
            )
        tokens = session.session_cost_tokens
        assert tokens == {"input": 0, "output": 0, "total": 0}


# ---------------------------------------------------------------------------
# _compact()
# ---------------------------------------------------------------------------

class TestCompact:
    def test_replaces_old_messages_with_summary_block(self, tmp_path: Path) -> None:
        with patch("worker_session.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = _make_response("Summary text")
            from worker_session import WorkerSession, _RECENT_MESSAGES_KEPT
            session = WorkerSession(
                _make_config(tmp_path / "ARCH.md", tmp_path / "SPEC.md"),
                _make_tracker(),
                MagicMock(),
            )
            # Seed more messages than _RECENT_MESSAGES_KEPT (10)
            session.messages = [
                {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
                for i in range(_RECENT_MESSAGES_KEPT + 5)
            ]
            session._compact()

        assert len(session.messages) == 2 + _RECENT_MESSAGES_KEPT
        assert session.messages[0]["role"] == "user"
        assert "Compacted session context" in session.messages[0]["content"]
        assert session.messages[1]["role"] == "assistant"

    def test_does_nothing_when_messages_fewer_than_kept(self, tmp_path: Path) -> None:
        with patch("worker_session.anthropic.Anthropic"):
            from worker_session import WorkerSession, _RECENT_MESSAGES_KEPT
            session = WorkerSession(
                _make_config(tmp_path / "ARCH.md", tmp_path / "SPEC.md"),
                _make_tracker(),
                MagicMock(),
            )
            session.messages = [{"role": "user", "content": "x"}]
            session._compact()
        assert len(session.messages) == 1  # unchanged


# ---------------------------------------------------------------------------
# _system_prompt()
# ---------------------------------------------------------------------------

class TestSystemPrompt:
    def test_includes_arch_and_spec_content(self, tmp_path: Path) -> None:
        arch = tmp_path / "ARCH.md"
        spec = tmp_path / "SPEC.md"
        arch.write_text("Use hexagonal architecture.")
        spec.write_text("Product is a CLI tool.")
        with patch("worker_session.anthropic.Anthropic"):
            from worker_session import WorkerSession
            session = WorkerSession(_make_config(arch, spec), _make_tracker(), MagicMock())
            prompt = session._system_prompt()
        assert "Use hexagonal architecture." in prompt
        assert "Product is a CLI tool." in prompt

    def test_handles_missing_arch_and_spec_files(self, tmp_path: Path) -> None:
        with patch("worker_session.anthropic.Anthropic"):
            from worker_session import WorkerSession
            session = WorkerSession(
                _make_config(tmp_path / "missing_arch.md", tmp_path / "missing_spec.md"),
                _make_tracker(),
                MagicMock(),
            )
            prompt = session._system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0
