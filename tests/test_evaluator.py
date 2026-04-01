import pytest
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from evaluator import ExitCodeEvaluator, EvalResult, BaseEvaluator, PlaywrightVisualEvaluator


class FakeConfig:
    build_command = "echo 'ok'"
    workspace_dir = Path("/tmp/workspace")
    playwright_target = "index.html"
    vision_model = "claude-3-5-sonnet-20241022"


# ─── ExitCodeEvaluator ────────────────────────────────────────────────────────

def test_evalresult_passed_on_exit_zero():
    config = FakeConfig()
    evaluator = ExitCodeEvaluator(config)
    with patch("evaluator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        result = evaluator.run()
    assert result.passed is True
    assert result.exit_code == 0
    assert "ok" in result.output


def test_evalresult_failed_on_nonzero_exit():
    config = FakeConfig()
    evaluator = ExitCodeEvaluator(config)
    with patch("evaluator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="build failed")
        result = evaluator.run()
    assert result.passed is False
    assert result.exit_code == 1
    assert "build failed" in result.output


def test_evalresult_captures_both_stdout_and_stderr():
    config = FakeConfig()
    evaluator = ExitCodeEvaluator(config)
    with patch("evaluator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="compiled\n", stderr="warning: unused var")
        result = evaluator.run()
    assert "compiled" in result.output
    assert "warning" in result.output


def test_exit_code_evaluator_is_base_evaluator():
    assert issubclass(ExitCodeEvaluator, BaseEvaluator)


# ─── PlaywrightVisualEvaluator — ABC contract ─────────────────────────────────

def test_playwright_evaluator_is_base_evaluator():
    assert issubclass(PlaywrightVisualEvaluator, BaseEvaluator)


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
        target_path=tmp_path / "nonexistent.html",
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

    with patch("evaluator.sync_playwright", None):
        result = ev._take_screenshot(
            target_path=target,
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

    with patch("evaluator.sync_playwright", return_value=mock_context_manager):
        # simulate screenshot writing the file
        screenshot_path.write_bytes(b"fakepng")
        result = ev._take_screenshot(target_path=target, screenshot_path=screenshot_path)

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

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="Score: 9/10. Clean layout. APPROVE")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message

    with patch("evaluator.anthropic.Anthropic", return_value=mock_client):
        result = ev._evaluate_with_vision(screenshot)

    assert result.passed is True
    assert "APPROVE" in result.output


def test_vision_returns_fail_when_response_contains_reject(tmp_path):
    config = FakeConfig()
    ev = PlaywrightVisualEvaluator(config)
    screenshot = tmp_path / ".harness_screenshot.png"
    screenshot.write_bytes(b"fakepng")

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="Score: 4/10. Boring AI slop. REJECT")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message

    with patch("evaluator.anthropic.Anthropic", return_value=mock_client):
        result = ev._evaluate_with_vision(screenshot)

    assert result.passed is False
    assert result.exit_code == 1


def test_vision_reject_check_is_case_insensitive(tmp_path):
    config = FakeConfig()
    ev = PlaywrightVisualEvaluator(config)
    screenshot = tmp_path / ".harness_screenshot.png"
    screenshot.write_bytes(b"fakepng")

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="Score: 3/10. reject this immediately.")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message

    with patch("evaluator.anthropic.Anthropic", return_value=mock_client):
        result = ev._evaluate_with_vision(screenshot)

    assert result.passed is False


def test_vision_handles_auth_error_gracefully(tmp_path):
    import anthropic as anthropic_module

    config = FakeConfig()
    ev = PlaywrightVisualEvaluator(config)
    screenshot = tmp_path / ".harness_screenshot.png"
    screenshot.write_bytes(b"fakepng")

    with patch("evaluator.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.side_effect = anthropic_module.AuthenticationError(
            message="Invalid API key",
            response=MagicMock(status_code=401, headers={}),
            body={},
        )
        result = ev._evaluate_with_vision(screenshot)

    assert result.passed is False
    assert "authentication" in result.output.lower()


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
