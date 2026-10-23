"""Rich progress bars + Ctrl-C handler."""

from __future__ import annotations

import asyncio
import signal
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

console = Console()

# Global cancellation flag
_cancelled = False


def is_cancelled() -> bool:
    return _cancelled


def setup_signal_handler() -> None:
    """Install Ctrl-C handler that sets cancellation flag.

    Silently skips if not running in the main thread (e.g. Streamlit).
    """
    import threading

    if threading.current_thread() is not threading.main_thread():
        return

    def _handler(sig, frame):
        global _cancelled
        if _cancelled:
            # Second Ctrl-C: hard exit
            console.print("\n[red bold]Force quit.[/red bold]")
            raise SystemExit(1)
        _cancelled = True
        console.print(
            "\n[yellow]Graceful shutdown requested. "
            "Current task will finish, then exit. Press Ctrl-C again to force.[/yellow]"
        )

    signal.signal(signal.SIGINT, _handler)


def reset_cancelled() -> None:
    global _cancelled
    _cancelled = False


def create_progress() -> Progress:
    """Create a Rich progress bar."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    )


def print_header(title: str) -> None:
    console.print(Panel(f"[bold magenta]{title}[/bold magenta]", expand=False))


def print_success(msg: str) -> None:
    console.print(f"[green]{msg}[/green]")


def print_warning(msg: str) -> None:
    console.print(f"[yellow]{msg}[/yellow]")


def print_error(msg: str) -> None:
    console.print(f"[red]{msg}[/red]")


def print_cost_table(costs: dict[str, float]) -> None:
    """Pretty-print a cost breakdown table."""
    table = Table(title="Estimated Cost Breakdown", show_header=True)
    table.add_column("Stage", style="cyan")
    table.add_column("Cost (USD)", justify="right", style="green")
    for stage, cost in costs.items():
        if stage != "total":
            table.add_row(stage, f"${cost:.4f}")
    table.add_section()
    table.add_row("[bold]Total[/bold]", f"[bold]${costs.get('total', 0):.4f}[/bold]")
    console.print(table)


def print_stage_summary(summary: dict[str, dict[str, int]]) -> None:
    """Pretty-print pipeline stage summary."""
    table = Table(title="Pipeline Status", show_header=True)
    table.add_column("Stage", style="cyan")
    table.add_column("Pending", justify="right")
    table.add_column("Running", justify="right", style="yellow")
    table.add_column("Done", justify="right", style="green")
    table.add_column("Failed", justify="right", style="red")
    for stage, counts in summary.items():
        table.add_row(
            stage,
            str(counts.get("pending", 0)),
            str(counts.get("running", 0)),
            str(counts.get("done", 0)),
            str(counts.get("failed", 0)),
        )
    console.print(table)
