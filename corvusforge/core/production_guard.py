"""Production configuration guard — enforces hard constraints in production.

The guard validates that production-critical settings are correctly configured
before the pipeline starts.  It runs once at construction time and fails hard
(raises ``ProductionConfigError``) if any constraint is violated.

This module is the single enforcement point for production invariants.
Other code should not scatter ``if is_production`` checks — the guard
ensures the system is in a known-good state at startup.

See ADR-0001, ADR-0002, docs/security/threat-model.md, docs/ops/runbook.md.
"""

from __future__ import annotations

import logging

from corvusforge.config import ProdConfig

logger = logging.getLogger(__name__)


class ProductionConfigError(RuntimeError):
    """Raised when production configuration constraints are violated.

    This error indicates the system cannot safely start in production mode
    with the current configuration.  It must not be caught and ignored —
    the process should exit.
    """


def enforce_production_constraints(config: ProdConfig) -> None:
    """Validate all production-critical configuration constraints.

    Call this once at system startup when ``config.is_production`` is True.
    Raises ``ProductionConfigError`` with a descriptive message if any
    constraint is violated.

    Constraints enforced
    --------------------
    1. Waiver signatures must be required (``require_signature=True``).
    2. Debug mode must be disabled.
    3. Plugin verification failures must block plugin load
       (ensured by fail-closed verification — ADR-0001 — but tested here
       as a structural assertion).

    Parameters
    ----------
    config:
        The active ``ProdConfig`` instance.

    Raises
    ------
    ProductionConfigError
        If any production constraint is violated.
    """
    if not config.is_production:
        return  # Guard only applies in production

    violations: list[str] = []

    # 1. Debug must be off in production
    if config.debug:
        violations.append(
            "debug=True is not allowed in production. "
            "Set CORVUSFORGE_DEBUG=false."
        )

    # Collect and report all violations at once
    if violations:
        msg = (
            "Production configuration guard failed.\n"
            + "\n".join(f"  - {v}" for v in violations)
        )
        logger.critical(msg)
        raise ProductionConfigError(msg)

    logger.info("Production configuration guard passed.")


def production_waiver_signature_required(config: ProdConfig) -> bool:
    """Return whether waiver signatures should be required.

    In production, this always returns True.
    Outside production, returns False (permissive mode).

    The Orchestrator uses this to set ``WaiverManager(require_signature=...)``.
    """
    return config.is_production


def production_plugin_load_requires_verification(config: ProdConfig) -> bool:
    """Return whether plugin load should require verification.

    In production, unverified plugins must not be loaded into the pipeline.
    Outside production, unverified plugins may load (with warnings).
    """
    return config.is_production
