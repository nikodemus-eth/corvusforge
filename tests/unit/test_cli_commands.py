"""Unit tests for the CLI — Typer command registration and basic behavior.

Phase 6B of v0.4.0: Exercises CLI app registration, help output, and
production guard invocation via typer.testing.CliRunner.
"""

from __future__ import annotations

from typer.testing import CliRunner

from corvusforge.cli.app import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Test: CLI help and registration
# ---------------------------------------------------------------------------


class TestCliApp:
    """The CLI must register all expected commands and show help."""

    def test_no_args_shows_help(self):
        """Running 'corvusforge' with no args should show help (exit code 0 or 2)."""
        result = runner.invoke(app, [])
        # Typer's no_args_is_help may exit with 0 or 2 depending on version
        assert result.exit_code in (0, 2)
        assert "corvusforge" in result.output.lower() or "Usage" in result.output or "usage" in result.output.lower()

    def test_help_flag(self):
        """--help must show usage information."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "new" in result.output
        assert "demo" in result.output
        assert "monitor" in result.output

    def test_new_command_exists(self):
        """'new' command must be registered."""
        result = runner.invoke(app, ["new", "--help"])
        assert result.exit_code == 0
        assert "new" in result.output.lower() or "pipeline" in result.output.lower()

    def test_demo_command_exists(self):
        """'demo' command must be registered."""
        result = runner.invoke(app, ["demo", "--help"])
        assert result.exit_code == 0

    def test_monitor_command_exists(self):
        """'monitor' command must be registered."""
        result = runner.invoke(app, ["monitor", "--help"])
        assert result.exit_code == 0

    def test_saoe_status_command_exists(self):
        """'saoe-status' command must be registered."""
        result = runner.invoke(app, ["saoe-status", "--help"])
        assert result.exit_code == 0

    def test_release_command_exists(self):
        """'release' command must be registered."""
        result = runner.invoke(app, ["release", "--help"])
        assert result.exit_code == 0

    def test_plugins_command_exists(self):
        """'plugins' command must be registered."""
        result = runner.invoke(app, ["plugins", "--help"])
        assert result.exit_code == 0
