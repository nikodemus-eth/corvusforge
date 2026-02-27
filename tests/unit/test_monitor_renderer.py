"""Unit tests for the MonitorRenderer.

Phase 6G of v0.4.0: Tests Rich panel output, state color mapping,
trust context display, and chain status rendering.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from rich.console import Console
from rich.panel import Panel

from corvusforge.models.stages import StageState
from corvusforge.monitor.projection import MonitorSnapshot, StageStatus
from corvusforge.monitor.renderer import MonitorRenderer, _STATE_STYLES, _STATE_ICONS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(
    chain_valid: bool = True,
    trust_healthy: bool = True,
    stages: list[StageStatus] | None = None,
) -> MonitorSnapshot:
    """Create a minimal MonitorSnapshot for testing."""
    default_stages = stages or [
        StageStatus(
            stage_id="s0_intake",
            display_name="Intake",
            state=StageState.PASSED,
        ),
        StageStatus(
            stage_id="s1_prerequisites",
            display_name="Prerequisites",
            state=StageState.RUNNING,
        ),
        StageStatus(
            stage_id="s2_environment",
            display_name="Environment",
            state=StageState.NOT_STARTED,
        ),
    ]
    return MonitorSnapshot(
        run_id="test-run-001",
        pipeline_version="0.4.0",
        stages=default_stages,
        chain_valid=chain_valid,
        trust_context_healthy=trust_healthy,
        last_updated=datetime(2026, 2, 27, 12, 0, 0, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Test: State mappings
# ---------------------------------------------------------------------------


class TestStateMappings:
    """State style and icon mappings must cover all StageState values."""

    def test_all_states_have_styles(self):
        """Every StageState must have an entry in _STATE_STYLES."""
        for state in StageState:
            assert state in _STATE_STYLES, f"Missing style for {state}"

    def test_all_states_have_icons(self):
        """Every StageState must have an entry in _STATE_ICONS."""
        for state in StageState:
            assert state in _STATE_ICONS, f"Missing icon for {state}"


# ---------------------------------------------------------------------------
# Test: Render snapshot
# ---------------------------------------------------------------------------


class TestRenderSnapshot:
    """render_snapshot must produce a Rich Panel with correct content."""

    def test_render_returns_panel(self):
        """render_snapshot should return a Rich Panel."""
        renderer = MonitorRenderer()
        snapshot = _make_snapshot()
        result = renderer.render_snapshot(snapshot)
        assert isinstance(result, Panel)

    def test_render_includes_run_id(self):
        """The rendered output should contain the run ID."""
        console = Console(file=None, force_terminal=True, width=120)
        renderer = MonitorRenderer(console=console)
        snapshot = _make_snapshot()
        panel = renderer.render_snapshot(snapshot)

        # Render to string to check content
        with console.capture() as capture:
            console.print(panel)
        output = capture.get()

        assert "test-run-001" in output

    def test_render_shows_chain_valid(self):
        """A valid chain should show 'valid' in the output."""
        console = Console(file=None, force_terminal=True, width=120)
        renderer = MonitorRenderer(console=console)
        snapshot = _make_snapshot(chain_valid=True)

        with console.capture() as capture:
            console.print(renderer.render_snapshot(snapshot))
        output = capture.get()

        assert "valid" in output.lower()

    def test_render_shows_chain_broken(self):
        """A broken chain should show 'BROKEN' in the output."""
        console = Console(file=None, force_terminal=True, width=120)
        renderer = MonitorRenderer(console=console)
        snapshot = _make_snapshot(chain_valid=False)

        with console.capture() as capture:
            console.print(renderer.render_snapshot(snapshot))
        output = capture.get()

        assert "BROKEN" in output

    def test_render_shows_trust_status(self):
        """Trust context health should appear in the output."""
        console = Console(file=None, force_terminal=True, width=120)
        renderer = MonitorRenderer(console=console)

        # Healthy
        snapshot_ok = _make_snapshot(trust_healthy=True)
        with console.capture() as capture:
            console.print(renderer.render_snapshot(snapshot_ok))
        assert "healthy" in capture.get().lower()

        # Unhealthy
        snapshot_bad = _make_snapshot(trust_healthy=False)
        with console.capture() as capture:
            console.print(renderer.render_snapshot(snapshot_bad))
        assert "INCOMPLETE" in capture.get()

    def test_print_chain_verification(self):
        """print_chain_verification should produce terminal output."""
        console = Console(file=None, force_terminal=True, width=120)
        renderer = MonitorRenderer(console=console)

        with console.capture() as capture:
            renderer.print_chain_verification("test-run", True)
        assert "valid" in capture.get().lower()

        with console.capture() as capture:
            renderer.print_chain_verification("test-run", False)
        assert "BROKEN" in capture.get()
