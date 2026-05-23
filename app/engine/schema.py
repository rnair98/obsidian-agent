from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import (  # pyright: ignore[reportMissingTypeStubs]
    add_messages,
)
from pydantic import BaseModel, ConfigDict, Field

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


class LocalVaultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["local"]
    path: Path


class GitVaultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["git"]
    url: str = Field(..., min_length=1)
    ref: str


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
