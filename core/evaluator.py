"""Evaluator — abstract base and concrete implementations for task quality gating."""

import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass


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
    """Responsibility: Placeholder for the 'Hater' visual evaluation module.

    Will use Playwright to spin up a browser, navigate to the workspace output,
    and perform visual regression tests against a baseline screenshot. Activate by
    setting evaluator: playwright in harness.yaml. Currently raises NotImplementedError
    to make its stub status explicit rather than silently passing all tasks.
    """

    def __init__(self, config) -> None:
        """Initialize with a config object. Playwright config will be read from harness.yaml."""
        self.config = config

    def run(self) -> EvalResult:
        """Run Playwright visual tests. Not yet implemented."""
        raise NotImplementedError(
            "PlaywrightVisualEvaluator is not yet implemented. "
            "Set evaluator: exit_code in harness.yaml to use ExitCodeEvaluator."
        )
