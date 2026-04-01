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
        self._console.print(
            "[bold]HarnessingLab Orchestrator v1.5 — Test-First Contract Negotiation[/bold]"
        )

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

    def interactive_pause(self, task_id: str) -> str:
        """Pause the pipeline and present the Observation Deck decision menu.

        Blocks until the human makes a valid choice. Returns one of:
          'commit'        — human approves, force commit regardless of evaluator
          'rollback'      — human rejects, force rollback
          'override_done' — human edited workspace/ manually, ready to re-evaluate

        For 'override_done', this method blocks a second time (waits for Enter)
        to give the human time to make manual edits before returning control.
        """
        self._console.print(
            f"\n[bold magenta]┌── Observation Deck ──────────────────────────────┐[/bold magenta]"
            f"\n[bold magenta]│[/bold magenta]  Task [bold]{task_id}[/bold] has been evaluated."
            f"\n[bold magenta]└──────────────────────────────────────────────────┘[/bold magenta]"
        )
        while True:
            choice = input(
                f"  (c) commit   (r) rollback   (o) override — edit workspace manually\n"
                f"  > "
            ).strip().lower()

            if choice == "c":
                return "commit"
            elif choice == "r":
                return "rollback"
            elif choice == "o":
                self._console.print(
                    "\n[bold yellow]  ⏸  Override Mode[/bold yellow]\n"
                    "  Edit workspace/ now. Press [bold]Enter[/bold] when done to re-evaluate."
                )
                input()
                return "override_done"
            else:
                self._console.print("[red]  Invalid choice. Enter c, r, or o.[/red]")

    def override_resumed(self) -> None:
        """Print that the override session ended and evaluation is re-running."""
        self._console.print("[dim]  Override complete — re-evaluating workspace...[/dim]")

    def contract_round(self, round_num: int, max_rounds: int, task_id: str) -> None:
        """Print NEGOTIATE phase: contract generation round."""
        self._console.print(
            f"[magenta]  NEGOTIATE: contract round {round_num}/{max_rounds} ({task_id})[/magenta]"
        )

    def contract_approved(self, task_id: str) -> None:
        """Contract verifier approved; contract will be locked in git."""
        self._console.print(f"[green]  ✓ Contract APPROVED for {task_id} — locked in git.[/green]")

    def contract_rejected(self, task_id: str, reason: str) -> None:
        """Contract verifier rejected; planner will retry or pause."""
        snippet = (reason[:500] + "…") if len(reason) > 500 else reason
        self._console.print(f"[yellow]  Contract REJECTED for {task_id}:[/yellow]\n[dim]{snippet}[/dim]")

    def contract_human_pause(self, task_id: str) -> None:
        """Planner retries exhausted — wait for human to fix SPEC or contract file."""
        self._console.print(
            f"\n[bold red]Contract negotiation exhausted for {task_id}.[/bold red]\n"
            "Edit SPEC.md or the contract test file, then press Enter to re-verify."
        )
