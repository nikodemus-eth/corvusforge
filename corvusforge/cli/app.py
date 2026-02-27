"""Main Typer application — imports and registers all CLI commands.

Entry point: ``corvusforge`` (configured via pyproject.toml console_scripts).

v0.3.0 commands: new, demo, monitor, saoe-status, release, ui, plugins.
"""

from __future__ import annotations

from pathlib import Path

import typer

from corvusforge.cli.commands.new import new_cmd
from corvusforge.cli.commands.demo import demo_cmd
from corvusforge.cli.commands.monitor_cmd import monitor_cmd
from corvusforge.cli.commands.saoe_status import saoe_status_cmd
from corvusforge.cli.commands.release import release_cmd

app = typer.Typer(
    name="corvusforge",
    help="Corvusforge: Deterministic, Auditable, Contract-Driven Coding Pipeline.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)

# Register subcommands
app.command(name="new", help="Create a new pipeline run.")(new_cmd)
app.command(name="demo", help="Run a complete demo pipeline with sample data.")(demo_cmd)
app.command(name="monitor", help="Show Build Monitor for a run.")(monitor_cmd)
app.command(name="saoe-status", help="Check saoe-mvp health.")(saoe_status_cmd)
app.command(name="release", help="Trigger Stage 7 (Release & Attestation).")(release_cmd)


@app.command(name="ui", help="Launch the Streamlit Build Monitor 2.0 dashboard.")
def ui_cmd(
    ledger_path: Path = typer.Option(
        Path(".corvusforge/ledger.db"), help="Path to the ledger database."
    ),
    data_dir: Path = typer.Option(
        Path(".openclaw-data"), help="Path to Thingstead fleet memory."
    ),
) -> None:
    """Launch the Corvusforge Build Monitor 2.0 (Streamlit)."""
    from corvusforge.dashboard import create_dashboard
    create_dashboard(ledger_path=ledger_path, data_dir=data_dir)


@app.command(name="plugins", help="List installed DLC plugins.")
def plugins_cmd(
    kind: str = typer.Option(None, help="Filter by plugin kind."),
) -> None:
    """List installed DLC plugins and their status."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    try:
        from corvusforge.plugins.registry import PluginRegistry, PluginKind

        registry = PluginRegistry()
        kind_filter = PluginKind(kind) if kind else None
        plugins = registry.list_plugins(kind=kind_filter, enabled_only=False)

        if not plugins:
            console.print("[dim]No plugins installed.[/dim]")
            return

        table = Table(title="Installed Plugins")
        table.add_column("Name", style="cyan")
        table.add_column("Version", style="green")
        table.add_column("Kind")
        table.add_column("Verified", justify="center")
        table.add_column("Enabled", justify="center")

        for p in plugins:
            verified = "[green]Yes[/green]" if p.verified else "[yellow]No[/yellow]"
            enabled = "[green]Yes[/green]" if p.enabled else "[red]No[/red]"
            table.add_row(p.name, p.version, p.kind, verified, enabled)

        console.print(table)
    except Exception as e:
        console.print(f"[red]Plugin registry error:[/red] {e}")


def main() -> None:
    """CLI entry point."""
    app()


if __name__ == "__main__":
    main()
