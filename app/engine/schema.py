from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True, slots=True)
class ResearchContext:
    pass


class ResearchState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    topic: str
    research_notes: list[str]
    experiments: list[str]
    code_context: list[str]
    sources: list[dict[str, str]]
    report: str
    zettelkasten_notes: list[dict[str, str]]
    reasoning: list[str]
    key_insights: list[str]


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(..., min_length=3)
