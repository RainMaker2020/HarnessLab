"""Unit tests for PlaywrightFunctionalEvaluator — RED phase (TDD)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(tmp_path: Path, *, target: str = "index.html") -> MagicMock:
    cfg = MagicMock()
    cfg.models = {"evaluator": "claude-3-5-sonnet-20241022"}
    cfg.workspace_dir = tmp_path
    cfg.playwright_target = target
    return cfg


def _make_task(task_id: str = "TASK_01", description: str = "Build login page") -> MagicMock:
    task = MagicMock()
    task.task_id = task_id
    task.description = description
    return task


def _make_llm_client(response_text: str) -> MagicMock:
    client = MagicMock()
    client.complete_text.return_value = response_text
    return client


def _make_playwright_mocks(
    *,
    html_content: str = "<html><body>App</body></html>",
    screenshot_bytes: bytes = b"\x89PNG\r\n",
    goto_raises: Exception | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Return (mock_ap_instance, mock_page) with AsyncMock internals wired up."""
    mock_page = MagicMock()
    mock_page.on = MagicMock()
    mock_page.content = AsyncMock(return_value=html_content)
    mock_page.screenshot = AsyncMock(return_value=screenshot_bytes)
    mock_page.query_selector_all = AsyncMock(return_value=[])

    if goto_raises:
        mock_page.goto = AsyncMock(side_effect=goto_raises)
    else:
        mock_page.goto = AsyncMock()

    mock_browser = MagicMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.close = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.chromium.launch = AsyncMock(return_value=mock_browser)

    mock_ap_instance = MagicMock()
    mock_ap_instance.__aenter__ = AsyncMock(return_value=mock_ctx)
    mock_ap_instance.__aexit__ = AsyncMock(return_value=False)

    return mock_ap_instance, mock_page


# ---------------------------------------------------------------------------
# Structural: is a BaseEvaluator
# ---------------------------------------------------------------------------

class TestPlaywrightFunctionalEvaluatorIsBaseEvaluator:
    def test_is_subclass_of_base_evaluator(self, tmp_path: Path) -> None:
        from evaluator import BaseEvaluator, PlaywrightFunctionalEvaluator
        assert issubclass(PlaywrightFunctionalEvaluator, BaseEvaluator)

    def test_instantiates_with_config(self, tmp_path: Path) -> None:
        from evaluator import PlaywrightFunctionalEvaluator
        ev = PlaywrightFunctionalEvaluator(_make_config(tmp_path))
        assert ev is not None


# ---------------------------------------------------------------------------
# _llm_qa() — LLM verdict layer
# ---------------------------------------------------------------------------

class TestLlmQa:
    def test_returns_passed_true_on_approve(self, tmp_path: Path) -> None:
        from evaluator import PlaywrightFunctionalEvaluator
        ev = PlaywrightFunctionalEvaluator(_make_config(tmp_path))
        with patch("evaluator.brain_client_for_role", return_value=_make_llm_client("Looks good.\n\nAPPROVE")):
            result = ev._llm_qa(
                html="<html></html>",
                console_errors=[],
                network_failures=[],
                task=_make_task(),
            )
        assert result.passed is True

    def test_returns_passed_false_on_reject(self, tmp_path: Path) -> None:
        from evaluator import PlaywrightFunctionalEvaluator
        ev = PlaywrightFunctionalEvaluator(_make_config(tmp_path))
        with patch("evaluator.brain_client_for_role", return_value=_make_llm_client("Broken UI.\n\nREJECT")):
            result = ev._llm_qa(
                html="<html></html>",
                console_errors=[],
                network_failures=[],
                task=_make_task(),
            )
        assert result.passed is False

    def test_console_errors_appear_in_prompt(self, tmp_path: Path) -> None:
        from evaluator import PlaywrightFunctionalEvaluator
        ev = PlaywrightFunctionalEvaluator(_make_config(tmp_path))
        captured_prompt: list[str] = []

        def fake_complete(model, text, *, max_tokens):
            captured_prompt.append(text)
            return "APPROVE"

        mock_client = MagicMock()
        mock_client.complete_text.side_effect = fake_complete

        with patch("evaluator.brain_client_for_role", return_value=mock_client):
            ev._llm_qa(
                html="<html></html>",
                console_errors=["Uncaught TypeError: cannot read 'foo'"],
                network_failures=[],
                task=_make_task(),
            )

        assert captured_prompt, "complete_text was not called"
        assert "Uncaught TypeError" in captured_prompt[0]

    def test_network_failures_appear_in_prompt(self, tmp_path: Path) -> None:
        from evaluator import PlaywrightFunctionalEvaluator
        ev = PlaywrightFunctionalEvaluator(_make_config(tmp_path))
        captured_prompt: list[str] = []

        def fake_complete(model, text, *, max_tokens):
            captured_prompt.append(text)
            return "APPROVE"

        mock_client = MagicMock()
        mock_client.complete_text.side_effect = fake_complete

        with patch("evaluator.brain_client_for_role", return_value=mock_client):
            ev._llm_qa(
                html="<html></html>",
                console_errors=[],
                network_failures=["GET /api/users 500"],
                task=_make_task(),
            )

        assert "GET /api/users 500" in captured_prompt[0]

    def test_contract_file_content_included_when_present(self, tmp_path: Path) -> None:
        contract_file = tmp_path / "TASK_01.contract.test.ts"
        contract_file.write_text("describe('login', () => { it('works', ...); });")
        from evaluator import PlaywrightFunctionalEvaluator
        ev = PlaywrightFunctionalEvaluator(_make_config(tmp_path))
        captured_prompt: list[str] = []

        def fake_complete(model, text, *, max_tokens):
            captured_prompt.append(text)
            return "APPROVE"

        mock_client = MagicMock()
        mock_client.complete_text.side_effect = fake_complete

        with patch("evaluator.brain_client_for_role", return_value=mock_client):
            ev._llm_qa(
                html="<html></html>",
                console_errors=[],
                network_failures=[],
                task=_make_task(task_id="TASK_01"),
            )

        assert "describe('login'" in captured_prompt[0]

    def test_prompt_works_without_contract_file(self, tmp_path: Path) -> None:
        from evaluator import PlaywrightFunctionalEvaluator
        ev = PlaywrightFunctionalEvaluator(_make_config(tmp_path))
        with patch("evaluator.brain_client_for_role", return_value=_make_llm_client("APPROVE")):
            result = ev._llm_qa(
                html="<html></html>",
                console_errors=[],
                network_failures=[],
                task=_make_task(task_id="TASK_99"),  # no contract file
            )
        # should not raise; result is EvalResult
        from evaluator import EvalResult
        assert isinstance(result, EvalResult)

    def test_llm_exception_returns_failed_result(self, tmp_path: Path) -> None:
        from evaluator import PlaywrightFunctionalEvaluator
        ev = PlaywrightFunctionalEvaluator(_make_config(tmp_path))

        class FakeAPIError(Exception):
            pass

        mock_client = MagicMock()
        mock_client.complete_text.side_effect = FakeAPIError("rate limit")

        with patch("evaluator.brain_client_for_role", return_value=mock_client):
            result = ev._llm_qa(
                html="<html></html>",
                console_errors=[],
                network_failures=[],
                task=_make_task(),
            )

        assert result.passed is False
        assert result.exit_code != 0

    def test_uses_correct_arg_order_for_brain_client(self, tmp_path: Path) -> None:
        """brain_client_for_role must be called as (config.models, 'evaluator')."""
        from evaluator import PlaywrightFunctionalEvaluator
        ev = PlaywrightFunctionalEvaluator(_make_config(tmp_path))
        captured_calls: list[tuple] = []

        def fake_brain_client(models, role):
            captured_calls.append((models, role))
            return _make_llm_client("APPROVE")

        with patch("evaluator.brain_client_for_role", side_effect=fake_brain_client):
            ev._llm_qa(
                html="<html></html>",
                console_errors=[],
                network_failures=[],
                task=_make_task(),
            )

        assert captured_calls, "brain_client_for_role was not called"
        models_arg, role_arg = captured_calls[0]
        assert role_arg == "evaluator"
        assert isinstance(models_arg, dict)  # config.models is a dict, not config object


# ---------------------------------------------------------------------------
# run() — async Playwright layer
# ---------------------------------------------------------------------------

class TestRunAsync:
    def test_page_load_failure_returns_failed_result(self, tmp_path: Path) -> None:
        (tmp_path / "index.html").write_text("<html></html>")
        from evaluator import EvalResult, PlaywrightFunctionalEvaluator
        ev = PlaywrightFunctionalEvaluator(_make_config(tmp_path))
        mock_ap, _ = _make_playwright_mocks(goto_raises=Exception("net::ERR_CONNECTION_REFUSED"))

        with patch("evaluator.async_playwright", return_value=mock_ap), \
             patch("evaluator.brain_client_for_role", return_value=_make_llm_client("APPROVE")):
            result = ev.run(task=_make_task())

        assert isinstance(result, EvalResult)
        assert result.passed is False
        assert "net::ERR_CONNECTION_REFUSED" in result.output

    def test_happy_path_approve_returns_passed_true(self, tmp_path: Path) -> None:
        (tmp_path / "index.html").write_text("<html><body>App</body></html>")
        from evaluator import EvalResult, PlaywrightFunctionalEvaluator
        ev = PlaywrightFunctionalEvaluator(_make_config(tmp_path))
        mock_ap, _ = _make_playwright_mocks()

        with patch("evaluator.async_playwright", return_value=mock_ap), \
             patch("evaluator.brain_client_for_role", return_value=_make_llm_client("All good.\n\nAPPROVE")):
            result = ev.run(task=_make_task())

        assert isinstance(result, EvalResult)
        assert result.passed is True

    def test_run_signature_accepts_edited_paths_and_task(self, tmp_path: Path) -> None:
        """run(edited_paths=None, task=None) must not raise TypeError."""
        from evaluator import PlaywrightFunctionalEvaluator
        ev = PlaywrightFunctionalEvaluator(_make_config(tmp_path))
        mock_ap, _ = _make_playwright_mocks()

        with patch("evaluator.async_playwright", return_value=mock_ap), \
             patch("evaluator.brain_client_for_role", return_value=_make_llm_client("APPROVE")):
            # Both keyword params should be accepted without TypeError
            result = ev.run(edited_paths=["src/app.ts"], task=_make_task())

        from evaluator import EvalResult
        assert isinstance(result, EvalResult)


# ---------------------------------------------------------------------------
# build_evaluator() routing
# ---------------------------------------------------------------------------

class TestBuildEvaluatorRouting:
    def test_playwright_functional_strategy_routes_to_evaluator(self, tmp_path: Path) -> None:
        from evaluator import PlaywrightFunctionalEvaluator
        from sub_orchestrator import build_evaluator

        cfg = MagicMock()
        cfg.evaluator_type = "playwright_functional"
        cfg.workspace_dir = tmp_path
        cfg.models = {}
        cfg.spec_doc = tmp_path / "SPEC.md"

        ev = build_evaluator(cfg)
        assert isinstance(ev, PlaywrightFunctionalEvaluator)
