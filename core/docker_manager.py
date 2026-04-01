"""DockerManager — manages the Docker sandbox container lifecycle."""

import subprocess
from pathlib import Path
from typing import Optional


class HarnessError(Exception):
    """Raised when a fatal harness-level error occurs that prevents safe continuation.

    Caught by main() to print a clean error and exit rather than a raw traceback.
    """


class DockerManager:
    """Responsibility: Manages the Docker sandbox container lifecycle.

    Handles container start, claude CLI execution inside the container, and cleanup.
    All subprocess calls are wrapped in try/except to prevent container failures from
    crashing the orchestrator silently. Reports errors through the ObservationDeck
    and raises HarnessError for fatal conditions requiring human intervention.
    """

    IMAGE_NAME = "harnesslab-sandbox"

    def __init__(self, config, ui) -> None:
        """Initialize with HarnessConfig and an ObservationDeck instance."""
        self.config = config
        self.ui = ui
        self._container_id: Optional[str] = None

    def start(self) -> None:
        """Start the Docker sandbox container, mounting workspace/ as a volume.

        Raises HarnessError if Docker is unavailable or the container fails to start.
        """
        workspace = str(self.config.workspace_dir)
        try:
            result = subprocess.run(
                [
                    "docker", "run", "-d",
                    "-v", f"{workspace}:/harness/workspace",
                    "--name", self.IMAGE_NAME,
                    self.IMAGE_NAME,
                    "tail", "-f", "/dev/null",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                raise HarnessError(
                    f"Docker container failed to start (exit {result.returncode}).\n"
                    f"stderr: {result.stderr.strip()}\n"
                    f"Ensure the image is built: docker build -t {self.IMAGE_NAME} ./sandbox"
                )
            self._container_id = result.stdout.strip()
            self.ui.info(f"Docker container started: {self._container_id[:12]}")
        except FileNotFoundError as exc:
            raise HarnessError(
                "Docker executable not found on PATH. "
                "Install Docker or set worker_mode: local in harness.yaml."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise HarnessError("Docker container startup timed out after 60s.") from exc
        except subprocess.SubprocessError as exc:
            raise HarnessError(f"Unexpected error during Docker startup: {exc}") from exc

    def exec_claude(self, prompt_file: Path, model_args: list) -> subprocess.CompletedProcess:
        """Execute the claude CLI inside the running container.

        Returns a CompletedProcess. On subprocess failure, returns a synthetic
        CompletedProcess with returncode=1 so the retry loop handles it gracefully
        rather than crashing the orchestrator.
        """
        if self._container_id is None:
            raise HarnessError("Docker container is not running. Call start() first.")

        prompt_content = prompt_file.read_text()
        try:
            return subprocess.run(
                ["docker", "exec", self._container_id,
                 "claude", "--print", prompt_content] + model_args,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            return self._synthetic_failure(
                f"docker exec not found — is Docker running? ({exc})"
            )
        except subprocess.SubprocessError as exc:
            return self._synthetic_failure(f"docker exec failed: {exc}")

    def stop(self) -> None:
        """Stop and remove the Docker container.

        Failure to stop is logged but does not raise — container cleanup is best-effort
        and should not abort an otherwise successful run.
        """
        if self._container_id is None:
            return
        try:
            subprocess.run(
                ["docker", "rm", "-f", self._container_id],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.ui.info(f"Docker container stopped: {self._container_id[:12]}")
        except (subprocess.SubprocessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            self.ui.info(f"Warning: could not stop container {self._container_id[:12]}: {exc}")
        finally:
            self._container_id = None

    @staticmethod
    def _synthetic_failure(reason: str) -> subprocess.CompletedProcess:
        """Build a fake CompletedProcess with exit code 1 for graceful retry handling."""
        return subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=f"[DockerManager] {reason}"
        )
