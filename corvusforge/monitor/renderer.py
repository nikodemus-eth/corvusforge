"""Rich terminal renderer for the Corvusforge Build Monitor.

Turns ``MonitorSnapshot`` into Rich renderables for terminal display,
with color-coded stage states and optional continuous ``Rich.Live`` mode.

Color scheme
------------
- green     : PASSED
- red       : FAILED
- yellow    : RUNNING
- dim       : NOT_STARTED
- magenta   : WAIVED
- bold red  : BLOCKED
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from corvusforge.models.stages import StageState

if TYPE_CHECKING:
    from corvusforge.core.run_ledger import RunLedger
    from corvusforge.monitor.projection import MonitorProjection, MonitorSnapshot


# ---------------------------------------------------------------------------
# State -> Rich style mapping
# ---------------------------------------------------------------------------

_STATE_STYLES: dict[StageState, str] = {
    StageState.PASSED: "bold green",
    StageState.FAILED: "bold red",
    StageState.RUNNING: "bold yellow",
    StageState.NOT_STARTED: "dim",
    StageState.WAIVED: "bold magenta",
    StageState.BLOCKED: "bold red",
}

_STATE_ICONS: dict[StageState, str] = {
    StageState.PASSED: "[green]PASSED[/green]",
    StageState.FAILED: "[bold red]FAILED[/bold red]",
    StageState.RUNNING: "[yellow]RUNNING[/yellow]",
    StageState.NOT_STARTED: "[dim]NOT STARTED[/dim]",
    StageState.WAIVED: "[magenta]WAIVED[/magenta]",
    StageState.BLOCKED: "[bold red]BLOCKED[/bold red]",
}


class MonitorRenderer:
    """Renders ``MonitorSnapshot`` as Rich terminal output.

    Parameters
    ----------
    console:
        Rich Console instance.  A new one is created if not provided.
    """

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    # ------------------------------------------------------------------
    # Single snapshot render
    # ------------------------------------------------------------------

    def render_snapshot(self, snapshot: MonitorSnapshot) -> Panel:
        """Render a MonitorSnapshot as a Rich Panel containing a Table.

        Returns a Rich renderable (Panel) that can be printed or used
        in Rich.Live.
        """
        table = self._build_stage_table(snapshot)

        # Summary footer
        summary_parts: list[str] = [
            f"[bold]Run:[/bold] {snapshot.run_id}",
            f"[bold]Version:[/bold] {snapshot.pipeline_version}",
            f"[bold]Progress:[/bold] {snapshot.completed_count}/{snapshot.total_stages}",
            f"[bold]Artifacts:[/bold] {snapshot.artifact_count}",
        ]

        if snapshot.active_waivers:
            summary_parts.append(
                f"[magenta][bold]Waivers:[/bold] {len(snapshot.active_waivers)}[/magenta]"
            )

        if snapshot.pending_clarifications:
            summary_parts.append(
                f"[yellow][bold]Pending Clarifications:[/bold] "
                f"{len(snapshot.pending_clarifications)}[/yellow]"
            )

        chain_status = (
            "[green]valid[/green]" if snapshot.chain_valid else "[bold red]BROKEN[/bold red]"
        )
        summary_parts.append(f"[bold]Chain:[/bold] {chain_status}")

        # Trust context health indicator
        if snapshot.trust_context_healthy:
            trust_status = "[green]healthy[/green]"
        else:
            trust_status = "[bold red]INCOMPLETE[/bold red]"
        summary_parts.append(f"[bold]Trust:[/bold] {trust_status}")

        summary = "  |  ".join(summary_parts)

        # Compose into a Panel
        from rich.console import Group

        panel_content = Group(table, Text(""), Text.from_markup(summary))

        return Panel(
            panel_content,
            title=f"[bold]Corvusforge Build Monitor[/bold]",
            subtitle=f"Last updated: {snapshot.last_updated.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            border_style="blue",
            padding=(1, 2),
        )

    def _build_stage_table(self, snapshot: MonitorSnapshot) -> Table:
        """Build a Rich Table of stage statuses."""
        table = Table(
            show_header=True,
            header_style="bold cyan",
            expand=True,
            show_lines=False,
            pad_edge=True,
        )

        table.add_column("#", style="dim", width=5, justify="right")
        table.add_column("Stage", min_width=25)
        table.add_column("State", min_width=14, justify="center")
        table.add_column("Details", min_width=20)
        table.add_column("Artifacts", justify="right", width=10)

        for i, stage in enumerate(snapshot.stages):
            ordinal = f"{i}"
            name_style = _STATE_STYLES.get(stage.state, "")
            state_display = _STATE_ICONS.get(stage.state, stage.state.value)

            # Build details column
            details_parts: list[str] = []
            if stage.block_reason:
                details_parts.append(f"[red]{stage.block_reason}[/red]")
            if stage.waiver_id:
                details_parts.append(f"[magenta]waiver: {stage.waiver_id[:12]}...[/magenta]")
            if stage.entered_at:
                details_parts.append(
                    f"[dim]{stage.entered_at.strftime('%H:%M:%S')}[/dim]"
                )
            details = " | ".join(details_parts) if details_parts else "[dim]-[/dim]"

            artifact_count = str(len(stage.artifact_refs)) if stage.artifact_refs else "[dim]0[/dim]"

            table.add_row(
                ordinal,
                f"[{name_style}]{stage.display_name}[/{name_style}]",
                state_display,
                details,
                artifact_count,
            )

        return table

    # ------------------------------------------------------------------
    # Continuous live rendering
    # ------------------------------------------------------------------

    def render_live(
        self,
        run_id: str,
        projection: MonitorProjection,
        *,
        refresh_hz: float = 2.0,
    ) -> None:
        """Continuously render the Build Monitor in Rich Live mode.

        Re-reads the ledger on every refresh cycle.  Press Ctrl+C to stop.

        Parameters
        ----------
        run_id:
            The pipeline run to monitor.
        projection:
            The MonitorProjection instance to read from.
        refresh_hz:
            Refresh rate in Hz (updates per second).  Default is 2.0.
        """
        interval = 1.0 / max(refresh_hz, 0.1)

        with Live(
            console=self.console,
            refresh_per_second=refresh_hz,
            transient=False,
        ) as live:
            try:
                while True:
                    snapshot = projection.snapshot(run_id)
                    panel = self.render_snapshot(snapshot)
                    live.update(panel)
                    time.sleep(interval)
            except KeyboardInterrupt:
                # Final snapshot on exit
                snapshot = projection.snapshot(run_id)
                panel = self.render_snapshot(snapshot)
                live.update(panel)

    # ------------------------------------------------------------------
    # Standalone print
    # ------------------------------------------------------------------

    def print_snapshot(self, snapshot: MonitorSnapshot) -> None:
        """Print a single snapshot to the console."""
        panel = self.render_snapshot(snapshot)
        self.console.print(panel)

    def print_chain_verification(self, run_id: str, valid: bool) -> None:
        """Print a chain verification result."""
        if valid:
            self.console.print(
                f"[green]Hash chain for run {run_id} is valid.[/green]"
            )
        else:
            self.console.print(
                f"[bold red]Hash chain for run {run_id} is BROKEN![/bold red]"
            )
