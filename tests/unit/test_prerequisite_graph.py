"""Tests for the PrerequisiteGraph — DAG, cascade blocking, unblocking."""

from __future__ import annotations

import pytest

from corvusforge.core.prerequisite_graph import (
    CyclicDependencyError,
    PrerequisiteGraph,
)
from corvusforge.models.stages import (
    StageDefinition,
    StageState,
)


class TestPrerequisiteGraph:
    def test_builds_from_defaults(self, graph: PrerequisiteGraph):
        assert len(graph.stage_ids) == 10

    def test_topological_order(self, graph: PrerequisiteGraph):
        ids = graph.stage_ids
        # s0 must come before s1
        assert ids.index("s0_intake") < ids.index("s1_prerequisites")
        # Both gates must come before verification
        assert ids.index("s55_accessibility") < ids.index("s6_verification")
        assert ids.index("s575_security") < ids.index("s6_verification")

    def test_prerequisites_met_initial(self, graph: PrerequisiteGraph):
        """s0 has no prerequisites, so it should be startable."""
        states = {sid: StageState.NOT_STARTED for sid in graph.stage_ids}
        assert graph.are_prerequisites_met("s0_intake", states) is True

    def test_prerequisites_not_met(self, graph: PrerequisiteGraph):
        """s1 requires s0 to be PASSED."""
        states = {sid: StageState.NOT_STARTED for sid in graph.stage_ids}
        assert graph.are_prerequisites_met("s1_prerequisites", states) is False

    def test_prerequisites_met_after_pass(self, graph: PrerequisiteGraph):
        states = {sid: StageState.NOT_STARTED for sid in graph.stage_ids}
        states["s0_intake"] = StageState.PASSED
        assert graph.are_prerequisites_met("s1_prerequisites", states) is True

    def test_prerequisites_met_with_waiver(self, graph: PrerequisiteGraph):
        states = {sid: StageState.NOT_STARTED for sid in graph.stage_ids}
        states["s0_intake"] = StageState.WAIVED
        assert graph.are_prerequisites_met("s1_prerequisites", states) is True

    def test_verification_requires_both_gates(self, graph: PrerequisiteGraph):
        states = {sid: StageState.PASSED for sid in graph.stage_ids}
        states["s575_security"] = StageState.NOT_STARTED
        assert graph.are_prerequisites_met("s6_verification", states) is False

    def test_cascade_block(self, graph: PrerequisiteGraph):
        states = {sid: StageState.NOT_STARTED for sid in graph.stage_ids}
        blocked = graph.cascade_block("s0_intake", states)
        # Everything downstream of s0 should be blocked
        assert "s1_prerequisites" in blocked
        assert "s7_release" in blocked
        assert "s0_intake" not in blocked  # the failed stage itself is not in blocked list

    def test_cascade_unblock(self, graph: PrerequisiteGraph):
        states = {sid: StageState.NOT_STARTED for sid in graph.stage_ids}
        # Block s1 first
        states["s1_prerequisites"] = StageState.BLOCKED
        states["s0_intake"] = StageState.PASSED
        unblocked = graph.cascade_unblock("s0_intake", states)
        assert "s1_prerequisites" in unblocked
        assert states["s1_prerequisites"] == StageState.NOT_STARTED

    def test_cyclic_dependency_rejected(self):
        with pytest.raises(CyclicDependencyError):
            PrerequisiteGraph([
                StageDefinition(stage_id="a", display_name="A", ordinal=0, prerequisites=["b"]),
                StageDefinition(stage_id="b", display_name="B", ordinal=1, prerequisites=["a"]),
            ])

    def test_get_dependents_transitive(self, graph: PrerequisiteGraph):
        deps = graph.get_dependents("s0_intake")
        # s0 is the root — everything depends on it transitively
        assert len(deps) == 9

    def test_get_blocking_reasons(self, graph: PrerequisiteGraph):
        states = {sid: StageState.NOT_STARTED for sid in graph.stage_ids}
        reasons = graph.get_blocking_reasons("s1_prerequisites", states)
        assert len(reasons) == 1
        assert "Intake" in reasons[0]
