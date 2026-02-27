"""``corvusforge monitor RUN_ID`` — show the Build Monitor for a pipeline run.

Displays the current state of all stages, artifact counts, waivers,
and hash chain status.  Supports continuous live mode and chain
verification.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from corvusforge.core.run_ledger import RunLedger
from corvusforge.monitor.projection import MonitorProjection
from corvusforge.monitor.renderer import MonitorRenderer

console = Console()


def monitor_cmd(
    run_id: str = typer.Argument(
        ...,
        help="The pipeline run ID to monitor.",
    ),
    live: bool = typer.Option(
        False,
        "--live",
        "-L",
        help="Enable continuous live monitoring mode (Ctrl+C to exit).",
    ),
    verify_chain: bool = typer.Option(
        False,
        "--verify-chain",
        "-V",
        help="Verify the hash chain integrity before displaying.",
    ),
    refresh_hz: float = typer.Option(
        2.0,
        "--refresh",
        "-r",
        help="Refresh rate in Hz for live mode.",
    ),
    ledger_db: str = typer.Option(
        ".corvusforge/ledger.db",
        "--ledger",
        "-l",
        help="Path to the ledger SQLite database.",
    ),
) -> None:
    """Show the Build Monitor for a pipeline run.

    The Build Monitor is a pure read-only projection over the Run Ledger.
    It never maintains its own state — every display re-reads the ledger.
    """
    db_path = Path(ledger_db)
    if not db_path.exists():
        console.print(f"[bold red]Ledger not found:[/bold red] {ledger_db}")
        console.print("[dim]Create a run first with: corvusforge new[/dim]")
        raise typer.Exit(code=1)

    ledger = RunLedger(db_path)
    projection = MonitorProjection(ledger)
    renderer = MonitorRenderer(console=console)

    # Check if the run exists
    entries = ledger.get_run_entries(run_id)
    if not entries:
        console.print(f"[bold red]Run not found:[/bold red] {run_id}")

        # List available runs
        all_runs = ledger.get_all_run_ids()
        if all_runs:
            console.print("\n[bold]Available runs:[/bold]")
            for rid in all_runs[:10]:
                console.print(f"  [cyan]{rid}[/cyan]")
            if len(all_runs) > 10:
                console.print(f"  [dim]... and {len(all_runs) - 10} more[/dim]")
        raise typer.Exit(code=1)

    # Verify chain if requested
    if verify_chain:
        console.print("[bold cyan]Verifying hash chain...[/bold cyan]")
        try:
            valid = ledger.verify_chain(run_id)
            renderer.print_chain_verification(run_id, valid)
        except Exception as exc:
            console.print(f"[bold red]Chain verification failed:[/bold red] {exc}")
            renderer.print_chain_verification(run_id, False)
        console.print()

    # Live or single-shot mode
    if live:
        console.print(
            f"[dim]Live monitoring run {run_id} at {refresh_hz} Hz. Press Ctrl+C to exit.[/dim]"
        )
        console.print()
        renderer.render_live(
            run_id,
            projection,
            refresh_hz=refresh_hz,
        )
    else:
        snapshot = projection.snapshot(run_id)
        renderer.print_snapshot(snapshot)
