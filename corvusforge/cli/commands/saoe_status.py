"""``corvusforge saoe-status`` — check saoe-mvp health.

Reports on the availability and status of the SAOE (Sovereign Agent
Operating Environment) components: vault, keys, audit log, and the
``age`` binary for encryption.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def _check_age_binary() -> tuple[bool, str]:
    """Check if the ``age`` binary is available on PATH."""
    age_path = shutil.which("age")
    if age_path:
        try:
            result = subprocess.run(
                ["age", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            version = result.stdout.strip() or result.stderr.strip() or "unknown"
            return True, f"{age_path} ({version})"
        except (subprocess.SubprocessError, OSError):
            return True, f"{age_path} (version check failed)"
    return False, "not found on PATH"


def _check_saoe_core() -> tuple[bool, str]:
    """Check if saoe_core is importable."""
    try:
        import saoe_core  # type: ignore[import-not-found]

        version = getattr(saoe_core, "__version__", "unknown")
        return True, f"v{version}"
    except ImportError:
        return False, "not installed (standalone mode)"


def _check_vault(saoe_core_path: Path | None) -> tuple[bool, str]:
    """Check if the SAOE vault directory exists and has expected structure."""
    if saoe_core_path is None:
        # Check default locations
        candidates = [
            Path(".saoe/vault"),
            Path.home() / ".saoe" / "vault",
        ]
    else:
        candidates = [saoe_core_path / "vault"]

    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            key_files = list(candidate.glob("*.key")) + list(candidate.glob("*.age"))
            return True, f"{candidate} ({len(key_files)} key files)"

    return False, "vault directory not found"


def _check_audit_log(saoe_core_path: Path | None) -> tuple[bool, str]:
    """Check if the SAOE audit log exists."""
    if saoe_core_path is None:
        candidates = [
            Path(".saoe/audit.log"),
            Path(".saoe/audit.db"),
            Path.home() / ".saoe" / "audit.log",
        ]
    else:
        candidates = [
            saoe_core_path / "audit.log",
            saoe_core_path / "audit.db",
        ]

    for candidate in candidates:
        if candidate.exists():
            size = candidate.stat().st_size
            return True, f"{candidate} ({size:,} bytes)"

    return False, "audit log not found"


def _check_keys(saoe_core_path: Path | None) -> tuple[bool, str]:
    """Check if signing keys are available."""
    try:
        from corvusforge.bridge.crypto_bridge import get_signing_key_fingerprint  # type: ignore[import-not-found]

        fp = get_signing_key_fingerprint()
        if fp:
            return True, f"fingerprint: {fp[:16]}..."
    except (ImportError, Exception):
        pass

    # Fallback: check for key files in standard locations
    key_dirs = [Path(".saoe/keys"), Path.home() / ".saoe" / "keys"]
    if saoe_core_path:
        key_dirs.insert(0, saoe_core_path / "keys")

    for key_dir in key_dirs:
        if key_dir.exists():
            keys = list(key_dir.glob("*.pub")) + list(key_dir.glob("*.key"))
            if keys:
                return True, f"{key_dir} ({len(keys)} key files)"

    return False, "no signing keys found"


def saoe_status_cmd(
    saoe_path: str = typer.Option(
        None,
        "--saoe-path",
        "-s",
        help="Path to the saoe-mvp / saoe-core directory.",
    ),
) -> None:
    """Check saoe-mvp health: vault, keys, audit log, and age binary.

    Reports the availability and status of each SAOE component.
    The pipeline can operate in standalone mode without SAOE, but
    some features (envelope signing, vault encryption) require it.
    """
    saoe_core_path = Path(saoe_path) if saoe_path else None

    checks: list[tuple[str, bool, str]] = []

    # Run all health checks
    ok, detail = _check_saoe_core()
    checks.append(("saoe-core", ok, detail))

    ok, detail = _check_vault(saoe_core_path)
    checks.append(("Vault", ok, detail))

    ok, detail = _check_keys(saoe_core_path)
    checks.append(("Signing Keys", ok, detail))

    ok, detail = _check_audit_log(saoe_core_path)
    checks.append(("Audit Log", ok, detail))

    ok, detail = _check_age_binary()
    checks.append(("age binary", ok, detail))

    # Build Rich table
    table = Table(
        show_header=True,
        header_style="bold cyan",
        expand=True,
    )
    table.add_column("Component", min_width=16)
    table.add_column("Status", width=10, justify="center")
    table.add_column("Details")

    all_ok = True
    for name, ok, detail in checks:
        status = "[green]OK[/green]" if ok else "[yellow]MISSING[/yellow]"
        if not ok:
            all_ok = False
        table.add_row(name, status, detail)

    # Overall status
    if all_ok:
        overall = "[bold green]All SAOE components available.[/bold green]"
        border_style = "green"
    else:
        overall = (
            "[bold yellow]Some SAOE components missing.[/bold yellow]\n"
            "[dim]The pipeline operates in standalone mode for missing components.[/dim]"
        )
        border_style = "yellow"

    console.print()
    console.print(
        Panel(
            table,
            title="[bold]SAOE Health Check[/bold]",
            subtitle=overall,
            border_style=border_style,
            padding=(1, 2),
        )
    )
    console.print()
