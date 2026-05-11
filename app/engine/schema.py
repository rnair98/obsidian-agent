from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True, slots=True)
class ResearchContext:
    vault: object | None = None


class ResearchState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    topic: str
    research_notes: list[str]
    experiments: list[str]
    code_context: list[str]
    sources: list[dict[str, str]]
    report: str
    zettelkasten_notes: list[dict[str, object]]
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
    ref: str | None = None


VaultRequest = Annotated[
    LocalVaultRequest | GitVaultRequest,
    Field(discriminator="type"),
]


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(..., min_length=3)
    vault: VaultRequest | None = None
