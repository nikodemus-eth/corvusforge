"""Version pinning model — ensures reproducibility (Invariant 10)."""

from pydantic import BaseModel, ConfigDict


class VersionPin(BaseModel):
    """Records all version pins for a pipeline run.

    Every run records its exact toolchain and ruleset versions so that
    any future replay uses identical semantics.
    """

    model_config = ConfigDict(frozen=True)

    pipeline_version: str = "0.1.0"
    schema_version: str = "2026-02"
    accessibility_ruleset_version: str = "wcag-2.1-aa"
    security_ruleset_version: str = "1.0.0"
    toolchain_version: str = "pydantic-v2.10+typer+rich+hatchling"
