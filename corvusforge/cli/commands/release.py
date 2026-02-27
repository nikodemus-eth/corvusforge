"""``corvusforge release RUN_ID`` — trigger Stage 7 (Release & Attestation).

Validates that all prerequisite stages (including the mandatory
accessibility and security gates) are satisfied, then transitions
Stage 7 to RUNNING and PASSED, recording the release in the ledger.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from corvusforge.core.orchestrator import Orchestrator
from corvusforge.core.run_ledger import RunLedger
from corvusforge.models.config import PipelineConfig
from corvusforge.models.stages import StageState
from corvusforge.monitor.projection import MonitorProjection
from corvusforge.monitor.renderer import MonitorRenderer

console = Console()

_RELEASE_STAGE = "s7_release"


def release_cmd(
    run_id: str = typer.Argument(
        ...,
        help="The pipeline run ID to release.",
    ),
    verify_chain: bool = typer.Option(
        True,
        "--verify-chain/--no-verify-chain",
        help="Verify hash chain integrity before releasing.",
    ),
    ledger_db: str = typer.Option(
        ".corvusforge/ledger.db",
        "--ledger",
        "-l",
        help="Path to the ledger SQLite database.",
    ),
    artifact_dir: str = typer.Option(
        ".corvusforge/artifacts",
        "--artifacts",
        "-a",
        help="Path to the artifact store directory.",
    ),
) -> None:
    """Trigger Stage 7 (Release & Attestation) for a pipeline run.

    Prerequisites:
    - All prior stages must be PASSED or WAIVED.
    - Hash chain integrity is verified (unless --no-verify-chain).
    - The release is recorded in the ledger with full traceability.
    """
    db_path = Path(ledger_db)
    if not db_path.exists():
        console.print(f"[bold red]Ledger not found:[/bold red] {ledger_db}")
        raise typer.Exit(code=1)

    config = PipelineConfig(
        artifact_store_path=Path(artifact_dir),
        ledger_db_path=db_path,
    )

    orchestrator = Orchestrator(config=config, run_id=run_id)
    projection = MonitorProjection(orchestrator.ledger)
    renderer = MonitorRenderer(console=console)

    # Resume the existing run
    states = orchestrator.resume_run(run_id)

    # Show current state
    console.print()
    snapshot = projection.snapshot(run_id)
    renderer.print_snapshot(snapshot)
    console.print()

    # Check release stage state
    release_state = states.get(_RELEASE_STAGE, StageState.NOT_STARTED)
    if release_state == StageState.PASSED:
        console.print(
            f"[bold yellow]Run {run_id} has already been released.[/bold yellow]"
        )
        raise typer.Exit(code=0)

    if release_state not in (StageState.NOT_STARTED,):
        console.print(
            f"[bold red]Release stage is in unexpected state: {release_state.value}[/bold red]"
        )
        raise typer.Exit(code=1)

    # Verify chain if requested
    if verify_chain:
        console.print("[bold cyan]Verifying hash chain integrity...[/bold cyan]")
        try:
            valid = orchestrator.verify_chain()
            renderer.print_chain_verification(run_id, valid)
            if not valid:
                console.print(
                    "[bold red]Release aborted: chain integrity check failed.[/bold red]"
                )
                raise typer.Exit(code=1)
        except Exception as exc:
            console.print(f"[bold red]Chain verification error:[/bold red] {exc}")
            raise typer.Exit(code=1)
        console.print()

    # Check prerequisites
    can_start, reasons = orchestrator.stage_machine.can_start(run_id, _RELEASE_STAGE)
    if not can_start:
        console.print("[bold red]Cannot release: prerequisites not met.[/bold red]")
        for reason in reasons:
            console.print(f"  [red]- {reason}[/red]")
        console.print(
            "\n[dim]All prior stages must be PASSED or WAIVED before releasing.[/dim]"
        )
        raise typer.Exit(code=1)

    # Execute the release stage
    console.print(f"[bold cyan]Triggering release for run {run_id}...[/bold cyan]")

    def _release_handler(handler_run_id: str, payload: dict) -> dict:
        """Release stage handler — records the attestation."""
        return {
            "status": "released",
            "run_id": handler_run_id,
            "attestation": "All stages passed. Release authorized.",
            "artifact_references": [],
        }

    orchestrator.register_stage_handler(_RELEASE_STAGE, _release_handler)

    try:
        orchestrator.execute_stage(_RELEASE_STAGE, {"action": "release"})
    except Exception as exc:
        console.print(f"[bold red]Release failed:[/bold red] {exc}")
        raise typer.Exit(code=1)

    # Show final state
    console.print()
    final_snapshot = projection.snapshot(run_id)
    renderer.print_snapshot(final_snapshot)

    console.print()
    console.print(
        Panel(
            "\n".join([
                f"[bold green]Release complete![/bold green]",
                "",
                f"[bold]Run ID:[/bold] {run_id}",
                f"[bold]Chain:[/bold]  {'valid' if final_snapshot.chain_valid else 'BROKEN'}",
                "",
                "[dim]The release has been recorded in the ledger with",
                "full traceability and hash chain integrity.[/dim]",
            ]),
            title="[bold]Release & Attestation[/bold]",
            border_style="green",
            padding=(1, 2),
        )
    )
