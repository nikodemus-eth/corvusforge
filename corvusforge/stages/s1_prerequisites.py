"""Stage 1 — Prerequisites Synthesis.

Analyses the work request (from Intake) and produces a dependency graph
that captures:
    - External tool/runtime requirements.
    - Version constraints for languages, frameworks, and libraries.
    - Ordered dependency resolution (topological sort).
    - Conflict detection between pinned versions.

The output is a ``DependencyGraph``-compatible dict that downstream stages
(especially Environment Readiness) consume to prepare the workspace.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, ClassVar

from corvusforge.core.hasher import content_address
from corvusforge.stages.base import BaseStage

logger = logging.getLogger(__name__)


class PrerequisitesSynthesisStage(BaseStage):
    """Stage 1: Prerequisites Synthesis — produces the dependency graph."""

    is_gate: ClassVar[bool] = False

    @property
    def stage_id(self) -> str:
        return "s1_prerequisites"

    @property
    def display_name(self) -> str:
        return "Prerequisites Synthesis"

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def execute(self, run_context: dict[str, Any]) -> dict[str, Any]:
        """Analyse the work request and build the dependency graph.

        Reads from *run_context*:
            ``run_config``  — the RunConfig produced by Stage 0.
            ``work_request`` — optional dict describing the requested work.

        Returns a structured dependency graph dict.
        """
        run_id: str = run_context.get("run_id", "")
        run_context.get("run_config")
        work_request: dict[str, Any] = run_context.get("work_request", {})

        # --- Discover required tools and runtimes ----------------------
        required_tools: list[dict[str, Any]] = self._discover_tools(
            work_request
        )

        # --- Discover language/framework dependencies ------------------
        language_deps: list[dict[str, Any]] = self._discover_language_deps(
            work_request
        )

        # --- Build the dependency graph --------------------------------
        graph_nodes: list[dict[str, Any]] = []
        graph_edges: list[dict[str, str]] = []

        for tool in required_tools:
            node_id = f"tool:{tool['name']}"
            graph_nodes.append({
                "node_id": node_id,
                "kind": "tool",
                "name": tool["name"],
                "version_constraint": tool.get("version", "*"),
                "required": tool.get("required", True),
            })

        for dep in language_deps:
            node_id = f"pkg:{dep['name']}"
            graph_nodes.append({
                "node_id": node_id,
                "kind": "package",
                "name": dep["name"],
                "version_constraint": dep.get("version", "*"),
                "required": dep.get("required", True),
            })
            # Add edges for declared dependencies between packages
            for upstream in dep.get("depends_on", []):
                graph_edges.append({
                    "from": f"pkg:{upstream}",
                    "to": node_id,
                })

        # --- Detect conflicts ------------------------------------------
        conflicts: list[dict[str, Any]] = self._detect_conflicts(graph_nodes)

        # --- Topological ordering (simple Kahn's for the dep graph) -----
        topo_order = self._topological_sort(graph_nodes, graph_edges)

        # --- Content-address the graph as an artifact -------------------
        dependency_graph: dict[str, Any] = {
            "nodes": graph_nodes,
            "edges": graph_edges,
            "topological_order": topo_order,
            "conflicts": conflicts,
        }
        graph_ref = content_address(dependency_graph)

        timestamp = datetime.now(timezone.utc).isoformat()

        return {
            "run_id": run_id,
            "dependency_graph": dependency_graph,
            "graph_artifact_ref": graph_ref,
            "total_nodes": len(graph_nodes),
            "total_edges": len(graph_edges),
            "conflict_count": len(conflicts),
            "resolved_at": timestamp,
            "_artifact_refs": [graph_ref],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _discover_tools(
        work_request: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Extract required tools from the work request.

        Falls back to sensible defaults when the work request does not
        explicitly declare tool requirements.
        """
        explicit = work_request.get("required_tools", [])
        if explicit:
            return [
                t if isinstance(t, dict) else {"name": str(t)}
                for t in explicit
            ]
        # Sensible defaults for a typical Python project
        return [
            {"name": "python", "version": ">=3.11", "required": True},
            {"name": "git", "version": "*", "required": True},
        ]

    @staticmethod
    def _discover_language_deps(
        work_request: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Extract language/framework dependencies from the work request."""
        explicit = work_request.get("dependencies", [])
        if explicit:
            return [
                d if isinstance(d, dict) else {"name": str(d)}
                for d in explicit
            ]
        return []

    @staticmethod
    def _detect_conflicts(
        nodes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Detect conflicting version constraints among nodes.

        Two nodes conflict if they share the same ``name`` but have
        incompatible version constraints.
        """
        seen: dict[str, list[dict[str, Any]]] = {}
        for node in nodes:
            seen.setdefault(node["name"], []).append(node)

        conflicts: list[dict[str, Any]] = []
        for name, entries in seen.items():
            if len(entries) > 1:
                constraints = [e.get("version_constraint", "*") for e in entries]
                if len(set(constraints)) > 1:
                    conflicts.append({
                        "name": name,
                        "conflicting_constraints": constraints,
                    })
        return conflicts

    @staticmethod
    def _topological_sort(
        nodes: list[dict[str, Any]],
        edges: list[dict[str, str]],
    ) -> list[str]:
        """Simple Kahn's algorithm topological sort over node_ids."""
        from collections import deque

        node_ids = {n["node_id"] for n in nodes}
        in_degree: dict[str, int] = {nid: 0 for nid in node_ids}
        adjacency: dict[str, list[str]] = {nid: [] for nid in node_ids}

        for edge in edges:
            src, dst = edge["from"], edge["to"]
            if src in adjacency and dst in in_degree:
                adjacency[src].append(dst)
                in_degree[dst] += 1

        queue: deque[str] = deque(
            nid for nid, deg in in_degree.items() if deg == 0
        )
        order: list[str] = []
        while queue:
            nid = queue.popleft()
            order.append(nid)
            for neighbour in adjacency.get(nid, []):
                in_degree[neighbour] -= 1
                if in_degree[neighbour] == 0:
                    queue.append(neighbour)

        return order
