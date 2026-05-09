from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field


class SearchQuery(BaseModel):
    """Structured boolean / semantic search query.

    All fields default to empty so partial requests (``{"raw": "x"}``) are
    accepted by the HTTP layer; the full structure is only used by the
    boolean-query builders.
    """

    raw: str = ""
    all_terms: list[str] = Field(default_factory=list)
    any_terms: list[str] = Field(default_factory=list)
    phrases: list[str] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)
    sites: list[str] = Field(default_factory=list)
    filetypes: list[str] = Field(default_factory=list)
    intitle: list[str] = Field(default_factory=list)
    inurl: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ResearchContext:
    search_limit: int = 15
    exa_search_type: str = "auto"
    fetch_code_context: bool = False
    seed_urls: list[str] = field(default_factory=list)
    experiment_snippets: list[str] = field(default_factory=list)


class ResearchState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    topic: str
    search_query: SearchQuery | None
    research_notes: list[str]
    experiments: list[str]
    code_context: list[str]
    sources: list[dict[str, str]]
    report: str
    zettelkasten_notes: list[dict[str, str]]
    memories: list[str]
    reasoning: list[str]
    key_insights: list[str]


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(..., min_length=3)
    seed_urls: list[str] = Field(default_factory=list)
    experiment_snippets: list[str] = Field(default_factory=list)
    search: SearchQuery | None = None
