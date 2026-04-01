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
        """Initialize with a config object exposing build_command and workspace_dir."""
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
