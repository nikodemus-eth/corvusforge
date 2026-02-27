"""``corvusforge demo`` — run a complete demo pipeline with sample data.

Executes every stage in the default pipeline with synthetic data,
displaying the Build Monitor at each transition to demonstrate the
pipeline flow.
"""

from __future__ import annotations

import time
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from corvusforge.core.orchestrator import Orchestrator
from corvusforge.models.config import PipelineConfig
from corvusforge.models.stages import DEFAULT_STAGE_DEFINITIONS, StageState
from corvusforge.monitor.projection import MonitorProjection
from corvusforge.monitor.renderer import MonitorRenderer

console = Console()


def demo_cmd(
    delay: float = typer.Option(
        0.5,
        "--delay",
        "-d",
        help="Delay in seconds between stage transitions for visual effect.",
    ),
    artifact_dir: str = typer.Option(
        ".corvusforge/artifacts",
        "--artifacts",
        help="Path to the artifact store directory.",
    ),
    ledger_db: str = typer.Option(
        ".corvusforge/demo-ledger.db",
        "--ledger",
        help="Path to the ledger SQLite database (uses demo-specific default).",
    ),
) -> None:
    """Run a complete demo pipeline with sample data.

    Creates a new run, executes all stages with synthetic data, and
    shows the Build Monitor at each transition.
    """
    config = PipelineConfig(
        project_name="corvusforge-demo",
        artifact_store_path=Path(artifact_dir),
        ledger_db_path=Path(ledger_db),
    )

    orchestrator = Orchestrator(config=config)
    projection = MonitorProjection(orchestrator.ledger)
    renderer = MonitorRenderer(console=console)

    # Header
    console.print()
    console.print(
        Panel(
            "[bold]Corvusforge Demo Pipeline[/bold]\n\n"
            "Running all stages with synthetic data.\n"
            "The Build Monitor updates at each transition.",
            border_style="cyan",
            padding=(1, 2),
        )
    )
    console.print()

    # Start run (Stage 0 Intake is handled by start_run)
    run_config = orchestrator.start_run(
        prerequisites=[{"type": "demo", "description": "Demo prerequisites"}]
    )
    run_id = orchestrator.run_id

    console.print(f"[bold green]Run created:[/bold green] {run_id}")
    console.print()

    # Show initial state
    snapshot = projection.snapshot(run_id)
    renderer.print_snapshot(snapshot)
    time.sleep(delay)

    # Define the stages to execute (s0_intake already done by start_run)
    stages_to_run = [
        sd for sd in DEFAULT_STAGE_DEFINITIONS if sd.stage_id != "s0_intake"
    ]

    # Sample handler that always succeeds
    def _demo_handler(handler_run_id: str, payload: dict) -> dict:
        """Synthetic stage handler for demo purposes."""
        return {
            "status": "passed",
            "note": f"Demo stage completed for run {handler_run_id}",
            "artifact_references": [],
        }

    # Register demo handlers for all stages
    for sd in stages_to_run:
        orchestrator.register_stage_handler(sd.stage_id, _demo_handler)

    # Execute each stage with Build Monitor display
    for sd in stages_to_run:
        console.print(f"\n[cyan]>>> Executing:[/cyan] [bold]{sd.display_name}[/bold] ({sd.stage_id})")
        time.sleep(delay)

        try:
            orchestrator.execute_stage(sd.stage_id, {"demo": True})
        except Exception as exc:
            console.print(f"[bold red]Stage {sd.stage_id} failed:[/bold red] {exc}")
            break

        # Show updated monitor
        snapshot = projection.snapshot(run_id)
        renderer.print_snapshot(snapshot)
        time.sleep(delay)

    # Final verification
    console.print()
    console.print("[bold cyan]Verifying hash chain integrity...[/bold cyan]")
    try:
        valid = orchestrator.verify_chain()
        renderer.print_chain_verification(run_id, valid)
    except Exception as exc:
        console.print(f"[bold red]Chain verification failed:[/bold red] {exc}")

    # Summary
    console.print()
    final_snapshot = projection.snapshot(run_id)
    console.print(
        Panel(
            "\n".join([
                f"[bold green]Demo Complete![/bold green]",
                "",
                f"[bold]Run ID:[/bold]      {run_id}",
                f"[bold]Stages:[/bold]      {final_snapshot.completed_count}/{final_snapshot.total_stages} completed",
                f"[bold]Artifacts:[/bold]   {final_snapshot.artifact_count}",
                f"[bold]Chain:[/bold]       {'valid' if final_snapshot.chain_valid else 'BROKEN'}",
            ]),
            title="[bold]Demo Summary[/bold]",
            border_style="green",
            padding=(1, 2),
        )
    )
