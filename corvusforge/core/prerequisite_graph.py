"""Prerequisite DAG with cascade blocking/unblocking (Invariants 4, 5, 6).

The graph enforces:
- No stage runs unless all prerequisites are PASSED or WAIVED.
- When a stage fails, all transitive dependents are BLOCKED.
- When a blocked stage is unblocked (upstream passes or waiver applied),
  dependents whose prerequisites are now met revert to NOT_STARTED.
"""

from __future__ import annotations

from collections import deque

from corvusforge.models.stages import StageDefinition, StageState


class PrerequisiteNotMetError(RuntimeError):
    """Raised when a stage cannot run because prerequisites are not met."""


class CyclicDependencyError(ValueError):
    """Raised when the prerequisite graph contains a cycle."""


class PrerequisiteGraph:
    """Directed acyclic graph of stage prerequisites.

    Built from StageDefinition.prerequisites at run creation time.
    """

    def __init__(self, stage_definitions: list[StageDefinition]) -> None:
        self._stages: dict[str, StageDefinition] = {
            sd.stage_id: sd for sd in stage_definitions
        }
        # Forward edges: stage_id -> list of prerequisite stage_ids
        self._prerequisites: dict[str, list[str]] = {
            sd.stage_id: list(sd.prerequisites) for sd in stage_definitions
        }
        # Reverse edges: stage_id -> list of stages that depend on it
        self._dependents: dict[str, list[str]] = {
            sd.stage_id: [] for sd in stage_definitions
        }
        for sd in stage_definitions:
            for prereq in sd.prerequisites:
                if prereq in self._dependents:
                    self._dependents[prereq].append(sd.stage_id)

        self._validate_no_cycles()

    def _validate_no_cycles(self) -> None:
        """Verify the graph is a DAG using topological sort (Kahn's algorithm)."""
        in_degree = {sid: len(prereqs) for sid, prereqs in self._prerequisites.items()}
        queue = deque(sid for sid, deg in in_degree.items() if deg == 0)
        visited = 0

        while queue:
            node = queue.popleft()
            visited += 1
            for dep in self._dependents.get(node, []):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)

        if visited != len(self._stages):
            raise CyclicDependencyError(
                f"Prerequisite graph has a cycle. "
                f"Visited {visited}/{len(self._stages)} stages."
            )

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_prerequisites(self, stage_id: str) -> list[str]:
        """Return direct prerequisite stage_ids for a stage."""
        return list(self._prerequisites.get(stage_id, []))

    def get_dependents(self, stage_id: str) -> list[str]:
        """Return all transitive dependent stage_ids (BFS)."""
        result = []
        queue = deque(self._dependents.get(stage_id, []))
        visited: set[str] = set()
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            result.append(node)
            queue.extend(self._dependents.get(node, []))
        return result

    def get_stage_definition(self, stage_id: str) -> StageDefinition:
        """Return the StageDefinition for a stage_id."""
        return self._stages[stage_id]

    @property
    def stage_ids(self) -> list[str]:
        """Return all stage_ids in topological order."""
        # Kahn's algorithm for topological sort
        in_degree = {sid: len(prereqs) for sid, prereqs in self._prerequisites.items()}
        queue = deque(
            sorted(
                (sid for sid, deg in in_degree.items() if deg == 0),
                key=lambda s: self._stages[s].ordinal,
            )
        )
        result = []
        while queue:
            node = queue.popleft()
            result.append(node)
            for dep in sorted(
                self._dependents.get(node, []),
                key=lambda s: self._stages[s].ordinal,
            ):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)
        return result

    # ------------------------------------------------------------------
    # Prerequisite checking
    # ------------------------------------------------------------------

    def are_prerequisites_met(
        self, stage_id: str, states: dict[str, StageState]
    ) -> bool:
        """Check if all prerequisites for a stage are PASSED or WAIVED."""
        for prereq in self._prerequisites.get(stage_id, []):
            if states.get(prereq) not in (StageState.PASSED, StageState.WAIVED):
                return False
        return True

    def get_blocking_reasons(
        self, stage_id: str, states: dict[str, StageState]
    ) -> list[str]:
        """Return human-readable reasons why a stage is blocked."""
        reasons = []
        for prereq in self._prerequisites.get(stage_id, []):
            state = states.get(prereq, StageState.NOT_STARTED)
            if state not in (StageState.PASSED, StageState.WAIVED):
                name = self._stages[prereq].display_name if prereq in self._stages else prereq
                reasons.append(f"{name} ({prereq}) is {state.value}")
        return reasons

    # ------------------------------------------------------------------
    # Cascade blocking / unblocking
    # ------------------------------------------------------------------

    def cascade_block(
        self, failed_stage_id: str, states: dict[str, StageState]
    ) -> list[str]:
        """When a stage fails, block all transitive dependents.

        Returns list of stage_ids that were newly blocked.
        """
        blocked: list[str] = []
        queue = deque(self._dependents.get(failed_stage_id, []))
        visited: set[str] = set()

        while queue:
            stage_id = queue.popleft()
            if stage_id in visited:
                continue
            visited.add(stage_id)

            current = states.get(stage_id, StageState.NOT_STARTED)
            if current in (StageState.NOT_STARTED, StageState.RUNNING):
                states[stage_id] = StageState.BLOCKED
                blocked.append(stage_id)

            queue.extend(self._dependents.get(stage_id, []))

        return blocked

    def cascade_unblock(
        self, passed_stage_id: str, states: dict[str, StageState]
    ) -> list[str]:
        """When a previously-failed stage passes, unblock eligible dependents.

        A dependent is unblocked only if ALL its prerequisites are now met.
        Returns list of stage_ids that were unblocked.
        """
        unblocked: list[str] = []
        for dependent_id in self._dependents.get(passed_stage_id, []):
            if states.get(dependent_id) == StageState.BLOCKED:
                if self.are_prerequisites_met(dependent_id, states):
                    states[dependent_id] = StageState.NOT_STARTED
                    unblocked.append(dependent_id)
        return unblocked
