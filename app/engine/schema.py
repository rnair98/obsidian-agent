from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import (  # pyright: ignore[reportMissingTypeStubs]
    add_messages,
)
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

if TYPE_CHECKING:
    from app.engine.vaults import VaultLayout


@dataclass(frozen=True, slots=True)
class ResearchContext:
    vault: "VaultLayout"


class ResearchState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    topic: str
    research_notes: list[str]
    experiments: list[str]
    code_context: list[str]
    sources: list["SourceState"]
    report: str
    zettelkasten_notes: list["ZettelNote"]
    reasoning: list[str]
    key_insights: list[str]
    # Rendered <vault_profile> block from the vault_profiler node.
    # Empty until the profiler node runs; consumed by the zettelkasten
    # node which prepends it to its own agent input as a SystemMessage.
    vault_profile: str


class LocalVaultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["local"]
    path: Path


class GitVaultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["git"]
    url: str = Field(..., min_length=1)
    ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


VaultRequest = Annotated[
    LocalVaultRequest | GitVaultRequest,
    Field(discriminator="type"),
]


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(..., min_length=3)
    vault: VaultRequest


class ZettelNote(TypedDict):
    id: str
    title: str
    content: str
    tags: list[str]


class SourceState(TypedDict):
    title: str
    url: str
    notes: str
    score: int


# ---------------------------------------------------------------------------
# HTTP response shape for POST /api/v1/workflows/run/{workflow_name}
#
# The raw ``ResearchState`` (messages, reasoning traces, full source dicts) is
# not a stable client contract — it carries internal LangGraph plumbing and
# noisy per-node accumulators. ``WorkflowRunResponse`` is the typed projection
# clients are expected to consume: it exposes the run identifier (for
# checkpointer replay), the resolved vault descriptor, references to every
# durable artifact materialized by the workflow, and a compact summary of
# state cardinalities. Built in ``app.engine.executor`` after graph
# invocation; see ARCHITECTURE.md §3 (Request Lifecycle).
# ---------------------------------------------------------------------------


class ArtifactRef(BaseModel):
    """Reference to a single materialized artifact on the vault."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        ...,
        description="Vault-relative POSIX path to the artifact.",
    )
    absolute_path: str = Field(
        ...,
        description="Backend-resolved absolute path to the artifact.",
    )


class ZettelArtifactRef(ArtifactRef):
    """Reference to a persisted Zettelkasten note, with note metadata."""

    id: str = Field(..., description="Note id as emitted by the agent.")
    title: str = Field(..., description="Note title as emitted by the agent.")
    tags: list[str] = Field(
        default_factory=list,
        description="Tags persisted to the note's frontmatter.",
    )


class RunArtifacts(BaseModel):
    """Bundle of every artifact a workflow may materialize to the vault."""

    model_config = ConfigDict(extra="forbid")

    report: ArtifactRef | None = Field(
        default=None,
        description="``outputs/report.md`` if the summarizer persisted one.",
    )
    sources_csv: ArtifactRef | None = Field(
        default=None,
        description="``outputs/sources.csv`` written by the persist node.",
    )
    zettels: list[ZettelArtifactRef] = Field(
        default_factory=list,
        description="One entry per Zettel note materialized under ``notes/``.",
    )
    memories: list[ArtifactRef] = Field(
        default_factory=list,
        description=(
            "Memory files newly written under ``.memories/`` by this run "
            "(diff vs. the pre-run listing)."
        ),
    )


class RunSummary(BaseModel):
    """Compact projection of ``ResearchState`` cardinalities + insights."""

    model_config = ConfigDict(extra="forbid")

    key_insights: list[str] = Field(default_factory=list)
    research_notes_count: int = 0
    sources_count: int = 0
    zettel_count: int = 0


class WorkflowRunResponse(BaseModel):
    """Typed 200 OK body for ``POST /api/v1/workflows/run/{workflow_name}``.

    Replaces the raw ``ResearchState`` dump so clients can rely on a stable
    contract and locate every artifact the run materialized.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(
        ...,
        description=(
            "LangGraph ``thread_id`` for this invocation. Pass back to the "
            "checkpointer to inspect/replay run state."
        ),
    )
    workflow: str = Field(
        ...,
        description="Workflow name that was invoked (mirrors the path param).",
    )
    topic: str
    vault: VaultRequest = Field(
        ...,
        description="Echo of the request's resolved vault descriptor.",
    )
    artifacts: RunArtifacts = Field(default_factory=RunArtifacts)
    summary: RunSummary = Field(default_factory=RunSummary)
