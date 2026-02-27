"""``corvusforge new`` — create a new pipeline run.

Creates a new run, initializes the ledger, sets up the artifact store
directory, and prints the run_id.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from corvusforge.core.orchestrator import Orchestrator
from corvusforge.models.config import PipelineConfig

console = Console()


def new_cmd(
    project_name: str = typer.Option(
        "corvusforge",
        "--project",
        "-p",
        help="Project name for this run.",
    ),
    artifact_dir: str = typer.Option(
        ".corvusforge/artifacts",
        "--artifacts",
        "-a",
        help="Path to the artifact store directory.",
    ),
    ledger_db: str = typer.Option(
        ".corvusforge/ledger.db",
        "--ledger",
        "-l",
        help="Path to the ledger SQLite database.",
    ),
) -> None:
    """Create a new pipeline run.

    Initializes the Run Ledger, sets up the artifact store directory,
    runs Stage 0 (Intake), and prints the run ID.
    """
    config = PipelineConfig(
        project_name=project_name,
        artifact_store_path=Path(artifact_dir),
        ledger_db_path=Path(ledger_db),
    )

    orchestrator = Orchestrator(config=config)
    run_config = orchestrator.start_run()

    # Display result
    console.print()
    console.print(
        Panel(
            "\n".join([
                f"[bold green]New pipeline run created![/bold green]",
                "",
                f"[bold]Run ID:[/bold]          {orchestrator.run_id}",
                f"[bold]Project:[/bold]         {project_name}",
                f"[bold]Artifact Store:[/bold]  {artifact_dir}",
                f"[bold]Ledger DB:[/bold]       {ledger_db}",
                f"[bold]Pipeline Version:[/bold] {config.version_pin.pipeline_version}",
                f"[bold]Stages:[/bold]          {len(run_config.stage_plan)}",
                "",
                f"[dim]Stage 0 (Intake) completed. Run is ready.[/dim]",
            ]),
            title="[bold]Corvusforge[/bold]",
            border_style="green",
            padding=(1, 2),
        )
    )
    console.print()

    # Print the run_id plainly for scripting
    console.print(f"[bold]{orchestrator.run_id}[/bold]")
