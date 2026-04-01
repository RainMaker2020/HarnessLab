"""Evaluator — abstract base and concrete implementations for task quality gating."""

import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Optional dependencies — imported at module level so tests can patch them via
# `patch("evaluator.anthropic.Anthropic")` and `patch("evaluator.sync_playwright")`.
# Set to None when not installed; concrete evaluators check before use.
try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]


@dataclass
class EvalResult:
    """Result of a single evaluator run."""

    passed: bool
    output: str
    exit_code: int


class BaseEvaluator(ABC):
    """Responsibility: Defines the contract for all evaluators in the pipeline.

    Any evaluator that determines whether Claude's output meets quality standards
    must implement this interface. Allows hot-swapping evaluation strategies
    (e.g., ExitCodeEvaluator → PlaywrightVisualEvaluator) without changing the
    main orchestration loop. The Orchestrator depends on this abstraction, not on
    any concrete implementation.
    """

    @abstractmethod
    def run(self) -> EvalResult:
        """Run evaluation against the workspace. Return an EvalResult."""


class ExitCodeEvaluator(BaseEvaluator):
    """Responsibility: Evaluates task success by running the configured build_command.

    The simplest concrete evaluator. Passes if build_command exits with code 0.
    Serves as the default pre-commit gatekeeper in harness.yaml (evaluator: exit_code).
    Replace with PlaywrightVisualEvaluator for visual regression testing.
    """

    def __init__(self, config) -> None:
        """Initialize with a config object exposing build_command and workspace_dir."""
        self.config = config

    def run(self) -> EvalResult:
        """Run build_command. Returns EvalResult with pass/fail and combined output."""
        try:
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
        except subprocess.SubprocessError as exc:
            return EvalResult(passed=False, output=f"SubprocessError: {exc}", exit_code=1)


class PlaywrightVisualEvaluator(BaseEvaluator):
    """Responsibility: The 'Eye' — visual quality gate using Playwright and Claude Vision.

    Pipeline:
      1. Run build_command. Fail fast if it exits non-zero.
      2. Launch headless Chromium via Playwright, navigate to playwright_target
         (a static HTML file relative to workspace/), take a full-page screenshot.
      3. Send the screenshot to Claude Vision (vision_model from harness.yaml).
      4. Ask: "Does this UI follow design principles? Score 1-10. If < 8, output REJECT."
      5. Pass if the response does not contain "REJECT"; fail otherwise.

    Activate by setting evaluator: playwright in harness.yaml.
    """

    VISION_PROMPT = (
        "You are a senior UI/UX reviewer and design quality gatekeeper. "
        "Examine this screenshot carefully.\n\n"
        "Answer these questions:\n"
        "1. Does this UI look like generic AI-generated slop? "
        "(boring layout, no visual hierarchy, Lorem Ipsum, grey boxes)\n"
        "2. Does it follow standard design principles? "
        "(visual hierarchy, appropriate spacing, readable typography, clear purpose)\n"
        "3. Score the overall design quality from 1 to 10.\n\n"
        "If the score is below 8, you MUST include the word REJECT in your response. "
        "If it passes (score >= 8), end with APPROVE."
    )

    SCREENSHOT_FILENAME = ".harness_screenshot.png"

    def __init__(self, config) -> None:
        """Initialize with a config exposing workspace_dir, playwright_target, vision_model."""
        self.config = config

    def run(self) -> EvalResult:
        """Run the full visual evaluation pipeline: build → screenshot → vision → result."""
        # Step 1: Build gate — fail fast before spinning up a browser
        build_result = self._run_build()
        if not build_result.passed:
            return build_result

        # Step 2: Take screenshot of the workspace output
        target = self.config.workspace_dir / getattr(self.config, "playwright_target", "index.html")
        screenshot_path = self.config.workspace_dir / self.SCREENSHOT_FILENAME
        screenshot_result = self._take_screenshot(target, screenshot_path)
        if not screenshot_result.passed:
            return screenshot_result

        # Step 3: Claude Vision quality gate
        return self._evaluate_with_vision(screenshot_path)

    def _run_build(self) -> EvalResult:
        """Run the build_command. Returns failure immediately if exit code is non-zero."""
        try:
            result = subprocess.run(
                self.config.build_command,
                shell=True,
                cwd=self.config.workspace_dir,
                capture_output=True,
                text=True,
            )
            combined = (result.stdout + result.stderr).strip()
            return EvalResult(
                passed=result.returncode == 0,
                output=combined,
                exit_code=result.returncode,
            )
        except subprocess.SubprocessError as exc:
            return EvalResult(passed=False, output=f"Build SubprocessError: {exc}", exit_code=1)

    def _take_screenshot(self, target_path: Path, screenshot_path: Path) -> EvalResult:
        """Launch headless Chromium, navigate to target_path, and save a full-page screenshot."""
        if not target_path.exists():
            return EvalResult(
                passed=False,
                output=(
                    f"Playwright target not found: {target_path}. "
                    f"Set playwright_target in harness.yaml to the correct HTML file."
                ),
                exit_code=1,
            )
        if sync_playwright is None:
            return EvalResult(
                passed=False,
                output="Playwright not installed. Run: pip install playwright && playwright install chromium",
                exit_code=1,
            )
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto(f"file://{target_path.resolve()}")
                    page.screenshot(path=str(screenshot_path), full_page=True)
                finally:
                    browser.close()

            return EvalResult(passed=True, output=f"Screenshot saved: {screenshot_path.name}", exit_code=0)
        except Exception as exc:  # noqa: BLE001 — Playwright raises many internal error types
            return EvalResult(passed=False, output=f"Playwright error: {exc}", exit_code=1)

    def _evaluate_with_vision(self, screenshot_path: Path) -> EvalResult:
        """Send the screenshot to Claude Vision and parse the APPROVE/REJECT verdict."""
        if anthropic is None:
            return EvalResult(
                passed=False,
                output="anthropic package not installed. Run: pip install anthropic",
                exit_code=1,
            )
        try:
            import base64

            with open(screenshot_path, "rb") as f:
                image_data = base64.standard_b64encode(f.read()).decode("utf-8")

            models = getattr(self.config, "models", {}) or {}
            vision_model = models.get("evaluator", "claude-3-5-sonnet-20241022")
            client = anthropic.Anthropic()
            message = client.messages.create(
                model=vision_model,
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_data,
                                },
                            },
                            {"type": "text", "text": self.VISION_PROMPT},
                        ],
                    }
                ],
            )

            response_text = message.content[0].text
            passed = "REJECT" not in response_text.upper()
            return EvalResult(
                passed=passed,
                output=response_text,
                exit_code=0 if passed else 1,
            )
        except anthropic.AuthenticationError as exc:
            return EvalResult(
                passed=False,
                output=f"Anthropic authentication failed. Check ANTHROPIC_API_KEY: {exc}",
                exit_code=1,
            )
        except anthropic.APIError as exc:
            return EvalResult(passed=False, output=f"Anthropic API error: {exc}", exit_code=1)
        except OSError as exc:
            return EvalResult(
                passed=False, output=f"Could not read screenshot file: {exc}", exit_code=1
            )
