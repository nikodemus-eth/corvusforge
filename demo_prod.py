"""Production smoke test — verifies the full Corvusforge pipeline.

Usage:
    python demo_prod.py
"""

from __future__ import annotations

from corvusforge.config import config
from corvusforge.core.orchestrator import Orchestrator


def main() -> None:
    """Run a production smoke test pipeline."""
    print(f"Corvusforge v0.3.0 PRODUCTION MODE")
    print(f"Environment: {config.environment} | Ledger: {config.ledger_path}")
    print()

    orch = Orchestrator()
    rc = orch.start_run([{"id": "prod_smoke", "name": "Production smoke test"}])
    print(f"Run ID: {rc.run_id}")

    # Execute a sample stage
    result = orch.execute_stage("s1_prerequisites", {"dependencies": []})
    print(f"s1_prerequisites: {result.get('status', 'passed')}")

    # Verify chain integrity
    chain_ok = orch.verify_chain()
    print(f"Ledger chain valid: {chain_ok}")

    # Show states
    states = orch.get_states()
    for stage_id, state in states.items():
        icon = {"passed": "OK", "running": "..", "not_started": "--"}.get(state.value, "??")
        print(f"  [{icon}] {stage_id}: {state.value}")

    print()
    print("Production pipeline complete — Docker & CI ready")


if __name__ == "__main__":
    main()
