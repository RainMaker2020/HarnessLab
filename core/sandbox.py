"""DockerManager — hardened Docker sandbox (runtime.* from harness.yaml)."""

import re
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from exceptions import HarnessError


class DockerManager:
    """Manages the Docker sandbox container lifecycle with configurable image and limits."""

    def __init__(self, config, ui) -> None:
        """Initialize with HarnessConfig and an ObservationDeck instance."""
        self.config = config
        self.ui = ui
        self._container_id: Optional[str] = None

    def _container_name(self) -> str:
        name = getattr(self.config.project, "name", "harness")
        safe = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")[:40] or "harness"
        return f"harness-{safe}-{uuid.uuid4().hex[:8]}"

    def start(self) -> None:
        """Start the Docker sandbox container, mounting workspace/ as a volume."""
        workspace = str(self.config.workspace_dir)
        image = getattr(self.config, "docker_image", None) or "harnesslab-sandbox:latest"
        memory = getattr(self.config, "docker_memory_limit", None) or "2g"
        net_ok = getattr(self.config, "docker_network_access", True)

        cmd: list[str] = [
            "docker",
            "run",
            "-d",
            "-v",
            f"{workspace}:/harness/workspace",
            "--memory",
            memory,
            "--name",
            self._container_name(),
        ]
        if not net_ok:
            cmd.extend(["--network", "none"])
        cmd.extend([image, "tail", "-f", "/dev/null"])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                raise HarnessError(
                    f"Docker container failed to start (exit {result.returncode}).\n"
                    f"stderr: {result.stderr.strip()}\n"
                    f"Ensure the image is built: docker build -t {image} ./sandbox"
                )
            self._container_id = result.stdout.strip()
            self.ui.info(f"Docker container started: {self._container_id[:12]}")
        except FileNotFoundError as exc:
            raise HarnessError(
                "Docker executable not found on PATH. "
                "Install Docker or set runtime.mode: local in harness.yaml."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise HarnessError("Docker container startup timed out after 60s.") from exc
        except subprocess.SubprocessError as exc:
            raise HarnessError(f"Unexpected error during Docker startup: {exc}") from exc

    def exec_claude(self, prompt_file: Path, model_args: list) -> subprocess.CompletedProcess:
        """Execute the claude CLI inside the running container."""
        if self._container_id is None:
            raise HarnessError("Docker container is not running. Call start() first.")

        prompt_content = prompt_file.read_text()
        try:
            return subprocess.run(
                ["docker", "exec", self._container_id, "claude", "--print", prompt_content]
                + model_args,
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
        """Stop and remove the Docker container."""
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
