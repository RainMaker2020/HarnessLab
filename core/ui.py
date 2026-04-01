"""ObservationDeck — centralized CLI output for the HarnessLab pipeline."""

from rich.console import Console


class ObservationDeck:
    """Responsibility: Single point of truth for all user-facing terminal output.

    Abstracts Rich console calls so Orchestrator logic contains zero formatting code.
    Every pipeline event (task start, success, failure, SOS, circuit breaker) routes
    through here, making the harness output easy to restyle or redirect without
    touching orchestration logic.
    """

    def __init__(self) -> None:
        """Initialize with a private Rich console."""
        self._console = Console()

    def harness_started(self) -> None:
        """Print the startup banner."""
        self._console.print("[bold]HarnessLab Orchestrator started.[/bold]")

    def task_start(self, task_id: str, description: str) -> None:
        """Print the task header divider."""
        self._console.print(f"\n[bold cyan]━━━ {task_id}: {description} ━━━[/bold cyan]")

    def attempt_start(self, attempt: int, max_retries: int) -> None:
        """Print the attempt counter."""
        self._console.print(f"[yellow]  Attempt {attempt}/{max_retries}[/yellow]")

    def baseline(self, head: str) -> None:
        """Print the git baseline HEAD."""
        self._console.print(f"[dim]  Baseline HEAD: {head[:8]}[/dim]")

    def prompt_written(self, filename: str) -> None:
        """Print confirmation that the prompt file was written."""
        self._console.print(f"[dim]  Prompt → {filename}[/dim]")

    def executing(self, task_id: str) -> None:
        """Print that the claude CLI is being invoked."""
        self._console.print(f"[blue]  Running claude for {task_id}...[/blue]")

    def success(self, task_id: str) -> None:
        """Print task success and commit confirmation."""
        self._console.print(f"[bold green]  ✓ {task_id} committed.[/bold green]")

    def failure(self, attempt: int, reason: str) -> None:
        """Print attempt failure and rollback notice."""
        self._console.print(f"[red]  ✗ Attempt {attempt} failed ({reason}). Rolled back.[/red]")

    def sos(self, task_id: str, stdout: str, stderr: str) -> None:
        """Print the SOS halt message. No rollback is performed on SOS."""
        self._console.print(
            f"\n[bold red]🚨 SOS (exit 2): Claude has requested human intervention.[/bold red]\n"
            f"[red]Task: {task_id}\nStdout:\n{stdout}\nStderr:\n{stderr}[/red]\n"
            f"[bold]No rollback performed. Halting. Review the workspace and restart.[/bold]"
        )

    def circuit_breaker(self, task_id: str, max_retries: int) -> None:
        """Print the circuit breaker halt message."""
        self._console.print(
            f"\n[bold red]CIRCUIT BREAKER TRIPPED: {task_id} failed "
            f"{max_retries} consecutive times.\n"
            f"Halting for human intervention. Check docs/history.json for details.[/bold red]"
        )

    def all_done(self) -> None:
        """Print the completion banner when PLAN.md is fully checked off."""
        self._console.print(
            "\n[bold green]✓ All tasks complete. PLAN.md is fully checked off.[/bold green]"
        )

    def workspace_initialized(self) -> None:
        """Print workspace git init notice."""
        self._console.print("[dim]Initialized workspace git repo.[/dim]")

    def fatal_error(self, message: str) -> None:
        """Print a fatal error that requires human intervention."""
        self._console.print(f"[bold red]FATAL: {message}[/bold red]")

    def info(self, message: str) -> None:
        """Print a dim informational message."""
        self._console.print(f"[dim]{message}[/dim]")
