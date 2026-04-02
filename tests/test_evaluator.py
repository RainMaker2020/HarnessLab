import pytest
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from harness.eval.evaluator import (
    BaseEvaluator,
    EvalResult,
    ExitCodeEvaluator,
    PlaywrightVisualEvaluator,
    parse_trailing_verdict,
)


def test_parse_trailing_verdict_last_line_approve():
    ok, amb = parse_trailing_verdict("Rationale\n\nAPPROVE")
    assert ok is True and amb is None


def test_parse_trailing_verdict_last_line_reject():
    ok, amb = parse_trailing_verdict("Rationale\n\nREJECT")
    assert ok is False and amb is None


def test_parse_trailing_verdict_last_token():
    ok, amb = parse_trailing_verdict("Score low.\nVerdict: APPROVE")
    assert ok is True and amb is None


def test_parse_trailing_verdict_ambiguous():
    ok, amb = parse_trailing_verdict("Maybe yes maybe no")
    assert ok is False and amb is not None


class FakeConfig:
    build_command = "echo 'ok'"
    workspace_dir = Path("/tmp/workspace")
    playwright_target = "index.html"
    vision_rubric = ""
    models = {
        "planner": "claude-sonnet-4-6",
        "generator": "claude-3-5-haiku",
        "evaluator": "claude-3-5-sonnet-20241022",
    }


# ─── ExitCodeEvaluator ────────────────────────────────────────────────────────

def test_evalresult_passed_on_exit_zero():
    config = FakeConfig()
    evaluator = ExitCodeEvaluator(config)
    with patch("harness.eval.evaluator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        result = evaluator.run()
    assert result.passed is True
    assert result.exit_code == 0
    assert "ok" in result.output


def test_evalresult_failed_on_nonzero_exit():
    config = FakeConfig()
    evaluator = ExitCodeEvaluator(config)
    with patch("harness.eval.evaluator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="build failed")
        result = evaluator.run()
    assert result.passed is False
    assert result.exit_code == 1
    assert "build failed" in result.output


def test_evalresult_captures_both_stdout_and_stderr():
    config = FakeConfig()
    evaluator = ExitCodeEvaluator(config)
    with patch("harness.eval.evaluator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="compiled\n", stderr="warning: unused var")
        result = evaluator.run()
    assert "compiled" in result.output
    assert "warning" in result.output


def test_exit_code_evaluator_is_base_evaluator():
    assert issubclass(ExitCodeEvaluator, BaseEvaluator)


# ─── PlaywrightVisualEvaluator — ABC contract ─────────────────────────────────

def test_playwright_evaluator_is_base_evaluator():
    assert issubclass(PlaywrightVisualEvaluator, BaseEvaluator)


def test_vision_prompt_includes_supplement(tmp_path: Path) -> None:
    sup = tmp_path / "extra.md"
    sup.write_text("SUPPLEMENT_BLOCK", encoding="utf-8")

    class ConfigWithSupplement(FakeConfig):
        vision_rubric = "BASE_RUBRIC"
        vision_rubric_supplement = sup

    ev = PlaywrightVisualEvaluator(ConfigWithSupplement())
    text = ev._vision_prompt_text()
    assert "BASE_RUBRIC" in text
    assert "SUPPLEMENT_BLOCK" in text
    assert "Repo design principles" in text


# ─── PlaywrightVisualEvaluator — _run_build ───────────────────────────────────

def test_playwright_run_fails_fast_when_build_fails():
    """If build_command exits non-zero, skip Playwright and Vision entirely."""
    ev = PlaywrightVisualEvaluator(FakeConfig())
    build_fail = EvalResult(passed=False, output="compile error", exit_code=1)

    with patch.object(ev, "_run_build", return_value=build_fail) as mock_build, \
         patch.object(ev, "_take_screenshot") as mock_shot, \
         patch.object(ev, "_evaluate_with_vision") as mock_vision:
        result = ev.run()

    assert result.passed is False
    assert result.output == "compile error"
    mock_shot.assert_not_called()
    mock_vision.assert_not_called()


# ─── PlaywrightVisualEvaluator — _take_screenshot ─────────────────────────────

def test_take_screenshot_returns_failure_if_target_missing(tmp_path):
    config = FakeConfig()
    config.workspace_dir = tmp_path
    ev = PlaywrightVisualEvaluator(config)

    result = ev._take_screenshot(
        target=tmp_path / "nonexistent.html",
        screenshot_path=tmp_path / ".harness_screenshot.png",
    )

    assert result.passed is False
    assert "not found" in result.output.lower()


def test_take_screenshot_returns_failure_when_sync_playwright_is_none(tmp_path):
    config = FakeConfig()
    config.workspace_dir = tmp_path
    ev = PlaywrightVisualEvaluator(config)
    target = tmp_path / "index.html"
    target.write_text("<html><body>Hello</body></html>")

    with patch("harness.eval.evaluator.sync_playwright", None):
        result = ev._take_screenshot(
            target=target,
            screenshot_path=tmp_path / ".harness_screenshot.png",
        )

    assert result.passed is False
    assert "playwright" in result.output.lower()


def test_take_screenshot_succeeds_with_mocked_playwright(tmp_path):
    config = FakeConfig()
    config.workspace_dir = tmp_path
    ev = PlaywrightVisualEvaluator(config)
    target = tmp_path / "index.html"
    target.write_text("<html><body>Hello</body></html>")
    screenshot_path = tmp_path / ".harness_screenshot.png"

    mock_page = MagicMock()
    mock_browser = MagicMock()
    mock_browser.new_page.return_value = mock_page
    mock_p = MagicMock()
    mock_p.chromium.launch.return_value = mock_browser

    mock_context_manager = MagicMock()
    mock_context_manager.__enter__ = MagicMock(return_value=mock_p)
    mock_context_manager.__exit__ = MagicMock(return_value=False)

    with patch("harness.eval.evaluator.sync_playwright", return_value=mock_context_manager):
        # simulate screenshot writing the file
        screenshot_path.write_bytes(b"fakepng")
        result = ev._take_screenshot(target=target, screenshot_path=screenshot_path)

    assert result.passed is True
    mock_page.goto.assert_called_once()
    mock_page.screenshot.assert_called_once_with(path=str(screenshot_path), full_page=True)
    mock_browser.close.assert_called_once()


# ─── PlaywrightVisualEvaluator — _evaluate_with_vision ────────────────────────

def test_vision_returns_pass_when_response_has_no_reject(tmp_path):
    config = FakeConfig()
    ev = PlaywrightVisualEvaluator(config)
    screenshot = tmp_path / ".harness_screenshot.png"
    screenshot.write_bytes(b"fakepng")

    mock_client = MagicMock()
    mock_client.complete_text_with_vision_png.return_value = "Score: 9/10. Clean layout. APPROVE"

    with patch("harness.eval.evaluator.brain_client_for_role", return_value=mock_client):
        result = ev._evaluate_with_vision(screenshot)

    assert result.passed is True
    assert "APPROVE" in result.output
    mock_client.complete_text_with_vision_png.assert_called_once()


def test_vision_returns_fail_when_response_contains_reject(tmp_path):
    config = FakeConfig()
    ev = PlaywrightVisualEvaluator(config)
    screenshot = tmp_path / ".harness_screenshot.png"
    screenshot.write_bytes(b"fakepng")

    mock_client = MagicMock()
    mock_client.complete_text_with_vision_png.return_value = "Score: 4/10. Boring AI slop. REJECT"

    with patch("harness.eval.evaluator.brain_client_for_role", return_value=mock_client):
        result = ev._evaluate_with_vision(screenshot)

    assert result.passed is False
    assert result.exit_code == 1


def test_vision_reject_check_is_case_insensitive(tmp_path):
    """Last line must read REJECT; lowercase ``reject`` is treated as failure (verdict parser)."""
    config = FakeConfig()
    ev = PlaywrightVisualEvaluator(config)
    screenshot = tmp_path / ".harness_screenshot.png"
    screenshot.write_bytes(b"fakepng")

    mock_client = MagicMock()
    mock_client.complete_text_with_vision_png.return_value = "Score: 3/10.\nreject"

    with patch("harness.eval.evaluator.brain_client_for_role", return_value=mock_client):
        result = ev._evaluate_with_vision(screenshot)

    assert result.passed is False


def test_vision_handles_auth_error_gracefully(tmp_path):
    config = FakeConfig()
    ev = PlaywrightVisualEvaluator(config)
    screenshot = tmp_path / ".harness_screenshot.png"
    screenshot.write_bytes(b"fakepng")

    class AuthenticationError(Exception):
        pass

    mock_client = MagicMock()
    mock_client.complete_text_with_vision_png.side_effect = AuthenticationError("Invalid API key")

    with patch("harness.eval.evaluator.brain_client_for_role", return_value=mock_client):
        result = ev._evaluate_with_vision(screenshot)

    assert result.passed is False
    assert "authentication" in result.output.lower()


def test_vision_evaluator_openai_provider_uses_factory_client(tmp_path):
    """Brain uses OpenAI path when evaluator_provider is openai (mocked client)."""
    config = FakeConfig()
    config.models = {
        "evaluator": "gpt-4o",
        "evaluator_provider": "openai",
    }
    ev = PlaywrightVisualEvaluator(config)
    screenshot = tmp_path / ".harness_screenshot.png"
    screenshot.write_bytes(b"\x89PNG\r\n")

    mock_client = MagicMock()
    mock_client.complete_text_with_vision_png.return_value = "Looks good.\nAPPROVE"

    with patch("harness.llm.llm_provider.LLMProviderFactory.create", return_value=mock_client):
        result = ev._evaluate_with_vision(screenshot)

    assert result.passed is True
    call_kw = mock_client.complete_text_with_vision_png.call_args
    assert call_kw[0][0] == "gpt-4o"
    assert call_kw[1]["png_bytes"] == b"\x89PNG\r\n"


# ─── PlaywrightVisualEvaluator — full pipeline integration ────────────────────

def test_full_pipeline_pass(tmp_path):
    """Build passes, screenshot taken, vision approves → EvalResult.passed=True."""
    config = FakeConfig()
    config.workspace_dir = tmp_path
    ev = PlaywrightVisualEvaluator(config)

    build_ok = EvalResult(passed=True, output="build ok", exit_code=0)
    shot_ok = EvalResult(passed=True, output="Screenshot saved", exit_code=0)
    vision_ok = EvalResult(passed=True, output="Score: 9. APPROVE", exit_code=0)

    with patch.object(ev, "_run_build", return_value=build_ok), \
         patch.object(ev, "_take_screenshot", return_value=shot_ok), \
         patch.object(ev, "_evaluate_with_vision", return_value=vision_ok):
        result = ev.run()

    assert result.passed is True


def test_full_pipeline_fail_on_vision_reject(tmp_path):
    """Build passes, screenshot taken, vision rejects → EvalResult.passed=False."""
    config = FakeConfig()
    config.workspace_dir = tmp_path
    ev = PlaywrightVisualEvaluator(config)

    with patch.object(ev, "_run_build", return_value=EvalResult(True, "ok", 0)), \
         patch.object(ev, "_take_screenshot", return_value=EvalResult(True, "Screenshot saved", 0)), \
         patch.object(ev, "_evaluate_with_vision", return_value=EvalResult(False, "REJECT", 1)):
        result = ev.run()

    assert result.passed is False


def test_exit_code_cross_file_regression_flags_downstream_file(tmp_path: Path):
    """TypeError in a file not edited → cross_file_regression with both files cited."""
    (tmp_path / "a.ts").write_text("export function foo() { return 1; }\n", encoding="utf-8")
    (tmp_path / "b.ts").write_text("export const z = 1;\n", encoding="utf-8")

    class C:
        build_command = "true"
        workspace_dir = tmp_path

    ev = ExitCodeEvaluator(C())
    combined = (
        "TypeError: cannot read property 'x' of undefined\n"
        "    at foo (b.ts:10:5)\n"
    )
    with patch("harness.eval.evaluator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout=combined, stderr="")
        result = ev.run(edited_paths=["a.ts"])

    assert result.passed is False
    assert result.cross_file_regression is True
    assert "CROSS-FILE REGRESSION" in result.output
    assert "b.ts" in result.output
    assert "a.ts" in result.output
