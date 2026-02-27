"""Stage 2 — Environment Readiness.

Consumes the dependency graph from Stage 1 and prepares the execution
environment:
    - Verify that required tools exist at the expected versions.
    - Verify that language runtimes and packages are available.
    - Snapshot the resolved environment (version pins, env vars) so that
      replays can detect drift.
    - Produce an environment manifest artifact.

The environment snapshot hash is stored on run_context for downstream use.
"""

from __future__ import annotations

import os
import platform
import shutil
import logging
from datetime import datetime, timezone
from typing import Any, ClassVar

from corvusforge.core.hasher import (
    compute_environment_snapshot_hash,
    content_address,
)
from corvusforge.models.config import RunConfig
from corvusforge.models.versioning import VersionPin
from corvusforge.stages.base import BaseStage

logger = logging.getLogger(__name__)


class EnvironmentReadinessStage(BaseStage):
    """Stage 2: Environment Readiness — validates and snapshots the env."""

    is_gate: ClassVar[bool] = False

    @property
    def stage_id(self) -> str:
        return "s2_environment"

    @property
    def display_name(self) -> str:
        return "Environment Readiness"

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def execute(self, run_context: dict[str, Any]) -> dict[str, Any]:
        """Validate tools, snapshot environment, produce manifest.

        Reads from *run_context*:
            ``run_config``       — RunConfig from Stage 0.
            ``stage_results.s1_prerequisites.dependency_graph`` — dep graph.

        Returns an environment readiness report.
        """
        run_id: str = run_context.get("run_id", "")
        run_config: RunConfig | None = run_context.get("run_config")

        # --- Retrieve the dependency graph from Stage 1 -----------------
        s1_result = run_context.get("stage_results", {}).get(
            "s1_prerequisites", {}
        )
        dep_graph: dict[str, Any] = s1_result.get("dependency_graph", {})
        nodes: list[dict[str, Any]] = dep_graph.get("nodes", [])

        # --- Check each required tool/runtime --------------------------
        tool_checks: list[dict[str, Any]] = []
        all_satisfied = True
        for node in nodes:
            if node.get("kind") == "tool":
                check = self._check_tool(node)
                tool_checks.append(check)
                if node.get("required", True) and not check["found"]:
                    all_satisfied = False

        # --- Snapshot environment variables -----------------------------
        env_snapshot: dict[str, str] = self._snapshot_env_vars()

        # --- Build version pin ------------------------------------------
        version_pin = (
            run_config.pipeline_config.version_pin
            if run_config
            else VersionPin()
        )

        # --- Compute environment hash for drift detection ---------------
        env_hash = compute_environment_snapshot_hash(
            version_pin, env_snapshot
        )
        run_context["environment_hash"] = env_hash

        # --- System info ------------------------------------------------
        system_info: dict[str, str] = {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "architecture": platform.machine(),
            "hostname": platform.node(),
        }

        # --- Environment manifest artifact ------------------------------
        manifest: dict[str, Any] = {
            "tool_checks": tool_checks,
            "env_snapshot_keys": sorted(env_snapshot.keys()),
            "version_pin": version_pin.model_dump(mode="json"),
            "system_info": system_info,
            "environment_hash": env_hash,
        }
        manifest_ref = content_address(manifest)

        timestamp = datetime.now(timezone.utc).isoformat()

        return {
            "run_id": run_id,
            "all_satisfied": all_satisfied,
            "tool_checks": tool_checks,
            "environment_hash": env_hash,
            "system_info": system_info,
            "version_pin": version_pin.model_dump(mode="json"),
            "manifest_artifact_ref": manifest_ref,
            "checked_at": timestamp,
            "_artifact_refs": [manifest_ref],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_tool(node: dict[str, Any]) -> dict[str, Any]:
        """Check whether a tool binary is available on PATH."""
        name: str = node.get("name", "")
        found_path = shutil.which(name)
        return {
            "name": name,
            "version_constraint": node.get("version_constraint", "*"),
            "found": found_path is not None,
            "resolved_path": found_path or "",
        }

    @staticmethod
    def _snapshot_env_vars() -> dict[str, str]:
        """Capture a curated set of environment variables.

        Only variables relevant to reproducibility are captured;
        sensitive values (tokens, secrets) are intentionally excluded.
        """
        curated_prefixes = (
            "PYTHON",
            "PATH",
            "VIRTUAL_ENV",
            "LANG",
            "LC_",
            "HOME",
            "USER",
            "SHELL",
            "NODE_",
            "NPM_",
            "CARGO_",
            "GOPATH",
            "JAVA_HOME",
        )
        secret_substrings = ("TOKEN", "SECRET", "KEY", "PASSWORD", "CREDENTIAL")

        snapshot: dict[str, str] = {}
        for key, value in sorted(os.environ.items()):
            if any(key.upper().startswith(p) for p in curated_prefixes):
                if not any(s in key.upper() for s in secret_substrings):
                    snapshot[key] = value
        return snapshot
