"""Evaluator — abstract base and concrete implementations for task quality gating."""

import re
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from llm_provider import brain_client_for_role

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]


DEFAULT_VISION_RUBRIC = (
    "You are a senior UI/UX reviewer and design quality gatekeeper. "
    "Examine this screenshot carefully.\n\n"
    "Answer these questions:\n"
    "1. Does this UI look like generic AI-generated slop? "
    "(boring layout, no visual hierarchy, Lorem Ipsum, grey boxes)\n"
    "2. Does it follow standard design principles? "
    "(visual hierarchy, appropriate spacing, readable typography, clear purpose)\n"
    "3. Score the overall design quality from 1 to 10.\n\n"
    "The harness reads only the last non-empty line of your reply. "
    "If the score is below 8, that final line MUST be exactly REJECT. "
    "If the score is 8 or above, that final line MUST be exactly APPROVE."
)


@dataclass
class EvalResult:
    """Result of a single evaluator run."""

    passed: bool
    output: str
    exit_code: int
    cross_file_regression: bool = False


def parse_trailing_verdict(text: str) -> tuple[bool, Optional[str]]:
    """Parse APPROVE/REJECT from the last non-empty line (avoids accidental REJECT substrings).

    Returns (passed, ambiguity_note). ambiguity_note is set only when the verdict cannot be read.
    """
    stripped = text.strip()
    if not stripped:
        return False, "Empty model response"

    lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
    last = lines[-1]
    for ch in ("*", "`", '"', "'"):
        last = last.replace(ch, "")
    last = last.strip().rstrip(".")

    upper = last.upper()
    if upper == "APPROVE":
        return True, None
    if upper == "REJECT":
        return False, None

    if ":" in last:
        tail = last.split(":")[-1].strip().upper().rstrip(".")
        if tail == "APPROVE":
            return True, None
        if tail == "REJECT":
            return False, None

    words = last.split()
    if words:
        tok = words[-1].upper().strip(".,;:!?")
        if tok == "APPROVE":
            return True, None
        if tok == "REJECT":
            return False, None

    return False, (
        f"Ambiguous verdict — end the response with a final line of exactly APPROVE or REJECT "
        f"(got: {last!r})"
    )


def _eval_result_from_llm_exception(exc: BaseException) -> EvalResult:
    """Map SDK errors from Brain LLM calls to an EvalResult."""
    name = type(exc).__name__
    msg = str(exc)
    if name == "AuthenticationError":
        return EvalResult(
            passed=False,
            output=f"LLM authentication failed. Check API keys / base URL: {msg}",
            exit_code=1,
        )
    return EvalResult(passed=False, output=f"{name}: {msg}", exit_code=1)


_RE_FILE_IN_ERR = re.compile(
    r"(?:^|[\s\(\[])([\w./@-]+\.(?:ts|tsx|js|jsx|mjs|cjs)):(\d+)(?::\d+)?"
)


def _norm_ws_path(path_str: str, workspace: Path) -> Optional[str]:
    """Return slash-normalized path relative to workspace if file exists."""
    ws = workspace.resolve()
    p = Path(path_str.strip())
    if p.is_absolute():
        try:
            rel = p.resolve().relative_to(ws)
            if (ws / rel).is_file():
                return str(rel).replace("\\", "/")
        except ValueError:
            return None
    cand = ws / path_str.replace("\\", "/")
    if cand.is_file():
        return str(cand.resolve().relative_to(ws)).replace("\\", "/")
    return None


def _extract_error_paths_from_build(output: str, workspace: Path) -> list[str]:
    """Collect workspace-relative paths mentioned in build / stack output."""
    found: list[str] = []
    for m in _RE_FILE_IN_ERR.finditer(output):
        rel = _norm_ws_path(m.group(1), workspace)
        if rel:
            found.append(rel)
    return list(dict.fromkeys(found))


def augment_build_result_with_cross_file_regression(
    combined_output: str,
    exit_code: int,
    workspace: Path,
    edited_paths: Optional[list[str]],
) -> EvalResult:
    """If build fails with TypeError/ReferenceError in a file not edited, flag cross-file regression."""
    if exit_code == 0:
        return EvalResult(
            passed=True,
            output=combined_output,
            exit_code=exit_code,
            cross_file_regression=False,
        )
    if not edited_paths:
        return EvalResult(
            passed=False,
            output=combined_output,
            exit_code=exit_code,
            cross_file_regression=False,
        )

    if "TypeError" not in combined_output and "ReferenceError" not in combined_output:
        return EvalResult(
            passed=False,
            output=combined_output,
            exit_code=exit_code,
            cross_file_regression=False,
        )

    edited = {p.replace("\\", "/") for p in edited_paths}
    err_paths = _extract_error_paths_from_build(combined_output, workspace)
    broken = [p for p in err_paths if p not in edited]

    if not broken:
        return EvalResult(
            passed=False,
            output=combined_output,
            exit_code=exit_code,
            cross_file_regression=False,
        )

    blocks: list[str] = [
        combined_output,
        "",
        "=== CROSS-FILE REGRESSION (Hater) ===",
        "Build failed with TypeError or ReferenceError in a file you did NOT edit.",
        f"Edited files (this sprint): {sorted(edited)}",
        f"Broken file(s) (downstream): {broken}",
        "",
    ]

    ws = workspace.resolve()
    for bpath in broken[:3]:
        bf = ws / bpath
        if bf.is_file():
            body = bf.read_text(encoding="utf-8", errors="replace")
            if len(body) > 12000:
                body = body[:12000] + "\n... [truncated]"
            blocks.append(f"--- Broken file: {bpath} ---\n```\n{body}\n```\n")

    for epath in sorted(edited)[:5]:
        ef = ws / epath
        if ef.is_file():
            body = ef.read_text(encoding="utf-8", errors="replace")
            if len(body) > 12000:
                body = body[:12000] + "\n... [truncated]"
            blocks.append(f"--- Edited file: {epath} ---\n```\n{body}\n```\n")

    msg = "\n".join(blocks)
    return EvalResult(
        passed=False,
        output=msg,
        exit_code=exit_code,
        cross_file_regression=True,
    )


class BaseEvaluator(ABC):
    """Responsibility: Defines the contract for all evaluators in the pipeline.

    Any evaluator that determines whether Claude's output meets quality standards
    must implement this interface. Allows hot-swapping evaluation strategies
    (e.g., ExitCodeEvaluator → PlaywrightVisualEvaluator) without changing the
    main orchestration loop. The Orchestrator depends on this abstraction, not on
    any concrete implementation.
    """

    @abstractmethod
    def run(self, edited_paths: Optional[list[str]] = None) -> EvalResult:
        """Run evaluation against the workspace. Return an EvalResult.

        edited_paths: workspace-relative paths changed since HEAD (for cross-file regression).
        """


class ExitCodeEvaluator(BaseEvaluator):
    """Responsibility: Evaluates task success by running the configured build_command.

    The simplest concrete evaluator. Passes if build_command exits with code 0.
    Serves as the default pre-commit gatekeeper in harness.yaml (evaluator: exit_code).
    Replace with PlaywrightVisualEvaluator for visual regression testing.
    """

    def __init__(self, config) -> None:
        """Initialize with a config object exposing build_command and workspace_dir."""
        self.config = config

    def run(self, edited_paths: Optional[list[str]] = None) -> EvalResult:
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
            if result.returncode == 0:
                return EvalResult(
                    passed=True,
                    output=combined_output,
                    exit_code=0,
                    cross_file_regression=False,
                )
            aug = augment_build_result_with_cross_file_regression(
                combined_output,
                result.returncode,
                Path(self.config.workspace_dir),
                edited_paths,
            )
            if aug.cross_file_regression:
                return aug
            return EvalResult(
                passed=False,
                output=combined_output,
                exit_code=result.returncode,
                cross_file_regression=False,
            )
        except subprocess.SubprocessError as exc:
            return EvalResult(passed=False, output=f"SubprocessError: {exc}", exit_code=1)


class PlaywrightVisualEvaluator(BaseEvaluator):
    """Responsibility: The 'Eye' — visual quality gate using Playwright and a Brain LLM (vision).

    Pipeline:
      1. Run build_command. Fail fast if it exits non-zero.
      2. Launch headless Chromium via Playwright, navigate to playwright_target
         (a static HTML file relative to workspace/), take a full-page screenshot.
      3. Send the screenshot to the configured Brain model (evaluator / evaluator_provider).
      4. Rubric asks for a score; the model must end with a line of exactly APPROVE or REJECT
         (see ``parse_trailing_verdict``).
      5. Pass if the final line is APPROVE; fail if REJECT or ambiguous.

    Activate by setting evaluation.strategy to playwright (or multimodal) in harness.yaml.
    """

    SCREENSHOT_FILENAME = ".harness_screenshot.png"

    def __init__(self, config) -> None:
        """Initialize with a config exposing workspace_dir, playwright_target, vision_model."""
        self.config = config

    def _vision_prompt_text(self) -> str:
        """Rubric from harness.yaml (evaluation.vision_rubric) or built-in default."""
        rubric = getattr(self.config, "vision_rubric", None)
        if rubric and str(rubric).strip():
            return str(rubric).strip()
        return DEFAULT_VISION_RUBRIC

    def _resolve_playwright_target(self) -> Union[Path, str]:
        """Static file under workspace, absolute path, or http(s) URL."""
        t = getattr(self.config, "playwright_target", "index.html")
        if isinstance(t, str) and (t.startswith("http://") or t.startswith("https://")):
            return t
        p = Path(t)
        if p.is_absolute():
            return p
        return self.config.workspace_dir / t

    def run(self, edited_paths: Optional[list[str]] = None) -> EvalResult:
        """Run the full visual evaluation pipeline: build → screenshot → vision → result."""
        # Step 1: Build gate — fail fast before spinning up a browser
        build_result = self._run_build(edited_paths)
        if not build_result.passed:
            return build_result

        # Step 2: Take screenshot of the workspace output
        target = self._resolve_playwright_target()
        screenshot_path = getattr(self.config, "screenshot_path", None) or (
            self.config.workspace_dir / self.SCREENSHOT_FILENAME
        )
        screenshot_result = self._take_screenshot(target, screenshot_path)
        if not screenshot_result.passed:
            return screenshot_result

        # Step 3: Brain LLM vision gate (provider from models.evaluator_provider)
        return self._evaluate_with_vision(screenshot_path)

    def _run_build(self, edited_paths: Optional[list[str]] = None) -> EvalResult:
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
            if result.returncode == 0:
                return EvalResult(
                    passed=True,
                    output=combined,
                    exit_code=0,
                    cross_file_regression=False,
                )
            aug = augment_build_result_with_cross_file_regression(
                combined,
                result.returncode,
                Path(self.config.workspace_dir),
                edited_paths,
            )
            if aug.cross_file_regression:
                return aug
            return EvalResult(
                passed=False,
                output=combined,
                exit_code=result.returncode,
                cross_file_regression=False,
            )
        except subprocess.SubprocessError as exc:
            return EvalResult(passed=False, output=f"Build SubprocessError: {exc}", exit_code=1)

    def _take_screenshot(
        self, target: Union[Path, str], screenshot_path: Path
    ) -> EvalResult:
        """Launch headless Chromium, navigate to file or URL, save a full-page screenshot."""
        if isinstance(target, Path) and not target.exists():
            return EvalResult(
                passed=False,
                output=(
                    f"Playwright target not found: {target}. "
                    "Set evaluation.playwright_target to a workspace file, absolute path, or http(s) URL."
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
                    if isinstance(target, str):
                        page.goto(target)
                    else:
                        page.goto(f"file://{target.resolve()}")
                    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(screenshot_path), full_page=True)
                finally:
                    browser.close()

            return EvalResult(passed=True, output=f"Screenshot saved: {screenshot_path.name}", exit_code=0)
        except Exception as exc:  # noqa: BLE001 — Playwright raises many internal error types
            return EvalResult(passed=False, output=f"Playwright error: {exc}", exit_code=1)

    def _evaluate_with_vision(self, screenshot_path: Path) -> EvalResult:
        """Send the screenshot to the configured Brain LLM and parse APPROVE/REJECT."""
        try:
            client = brain_client_for_role(getattr(self.config, "models", None), "evaluator")
        except (ValueError, RuntimeError) as exc:
            return EvalResult(passed=False, output=str(exc), exit_code=1)

        models = getattr(self.config, "models", {}) or {}
        vision_model = models.get("evaluator", "claude-3-5-sonnet-20241022")
        try:
            png_bytes = screenshot_path.read_bytes()
        except OSError as exc:
            return EvalResult(passed=False, output=f"Could not read screenshot file: {exc}", exit_code=1)

        try:
            response_text = client.complete_text_with_vision_png(
                vision_model,
                png_bytes=png_bytes,
                text_prompt=self._vision_prompt_text(),
                max_tokens=1024,
            )
        except Exception as exc:  # noqa: BLE001 — Brain SDKs raise varied types
            return _eval_result_from_llm_exception(exc)

        if not response_text.strip():
            return EvalResult(
                passed=False,
                output="Brain LLM returned no text content in the vision response.",
                exit_code=1,
            )
        passed, amb = parse_trailing_verdict(response_text)
        out = response_text
        if amb is not None:
            out = f"{response_text}\n---\n{amb}"
            passed = False
        return EvalResult(
            passed=passed,
            output=out,
            exit_code=0 if passed else 1,
        )


CONTRACT_VERIFY_PROMPT = (
    "You are a strict specification auditor. You will receive SPEC.md, a task ID and description, "
    "and a TypeScript test file that is proposed as the formal contract for that task.\n\n"
    "Decide whether the tests are a faithful 1:1 mapping of the requirements in SPEC.md that apply "
    "to this task. Every requirement that SPEC imposes for this task must have a corresponding test; "
    "tests must not assert unrelated or invented requirements.\n\n"
    "Reply with a short rationale, then end with exactly one line: APPROVE or REJECT.\n"
    "If anything is missing, ambiguous, or over-scoped, respond with REJECT."
)


class ContractVerifier:
    """NEGOTIATE-phase gate: Brain LLM verifies contract tests against SPEC (API, provider from config)."""

    def __init__(self, config) -> None:
        self.config = config

    def verify_contract(
        self, task_id: str, task_description: str, contract_path: Path
    ) -> EvalResult:
        """Return passed=True if the contract is an acceptable 1:1 map to SPEC for this task."""
        try:
            client = brain_client_for_role(getattr(self.config, "models", None), "contract_verifier")
        except (ValueError, RuntimeError) as exc:
            return EvalResult(passed=False, output=str(exc), exit_code=1)

        if not contract_path.exists():
            return EvalResult(
                passed=False,
                output=f"Contract file not found: {contract_path}",
                exit_code=1,
            )
        try:
            spec_text = self.config.spec_doc.read_text()
            contract_text = contract_path.read_text(encoding="utf-8")
        except OSError as exc:
            return EvalResult(passed=False, output=f"Could not read files: {exc}", exit_code=1)
        models = getattr(self.config, "models", {}) or {}
        model = models.get("contract_verifier") or models.get("evaluator") or "claude-3-5-sonnet-20241022"

        user_block = (
            f"{CONTRACT_VERIFY_PROMPT}\n\n"
            f"## Task ID\n{task_id}\n\n"
            f"## Task description\n{task_description}\n\n"
            "## SPEC.md\n"
            f"{spec_text}\n\n"
            "## Proposed contract tests\n"
            f"```typescript\n{contract_text}\n```\n"
        )

        try:
            response_text = client.complete_text(model, user_block, max_tokens=2048)
        except Exception as exc:  # noqa: BLE001
            return _eval_result_from_llm_exception(exc)

        if not response_text.strip():
            return EvalResult(
                passed=False,
                output="Brain LLM returned no text content in the contract verification response.",
                exit_code=1,
            )
        passed, amb = parse_trailing_verdict(response_text)
        out = response_text
        if amb is not None:
            out = f"{response_text}\n---\n{amb}"
            passed = False
        return EvalResult(
            passed=passed,
            output=out,
            exit_code=0 if passed else 1,
        )
