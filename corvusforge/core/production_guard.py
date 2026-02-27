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

# Default trust root keys that MUST be configured in production.
# These map to ProdConfig field names.  If config.trust_context_required_keys
# is empty, these are used as the production default.
PRODUCTION_REQUIRED_TRUST_KEYS: list[str] = [
    "plugin_trust_root",
    "waiver_signing_key",
]


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
    1. Debug mode must be disabled.
    2. Trust root keys required by the environment profile must be configured
       (non-empty).  Defaults to ``plugin_trust_root`` and ``waiver_signing_key``.

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

    # 2. Trust root keys must be configured
    required_keys = config.trust_context_required_keys or PRODUCTION_REQUIRED_TRUST_KEYS
    for key_name in required_keys:
        value = getattr(config, key_name, "")
        if not value:
            violations.append(
                f"Trust root key '{key_name}' is required in production but not configured. "
                f"Set CORVUSFORGE_{key_name.upper()}."
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


def validate_trust_context_completeness(
    trust_context: dict[str, str],
    required_keys: list[str] | None = None,
) -> list[str]:
    """Check a trust context dict for missing or empty required fingerprints.

    Returns a list of warning strings — empty means healthy.

    Parameters
    ----------
    trust_context:
        The ``trust_context`` dict from a ``LedgerEntry``.
    required_keys:
        Config field names that must have non-empty fingerprints.
        Defaults to ``PRODUCTION_REQUIRED_TRUST_KEYS``.

    Returns
    -------
    list[str]
        Warning messages for each missing or empty fingerprint.
    """
    # Map config field names to trust_context fingerprint key names
    _FIELD_TO_FP = {
        "plugin_trust_root": "plugin_trust_root_fp",
        "waiver_signing_key": "waiver_signing_key_fp",
        "anchor_key": "anchor_key_fp",
    }

    required = required_keys or PRODUCTION_REQUIRED_TRUST_KEYS
    warnings: list[str] = []

    for key_name in required:
        fp_key = _FIELD_TO_FP.get(key_name, f"{key_name}_fp")
        fp_value = trust_context.get(fp_key, "")
        if not fp_value:
            warnings.append(
                f"Trust context missing required fingerprint: {fp_key}"
            )

    return warnings


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
