from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class LLMConfig(TypedDict):
    model: str | None = None
    temperature: float | None = None
    base_url: str | None = None


class SearchQuery(TypedDict):
    raw: str
    all_terms: list[str]
    any_terms: list[str]
    phrases: list[str]
    excluded: list[str]
    sites: list[str]
    filetypes: list[str]
    intitle: list[str]
    inurl: list[str]


@dataclass
class ResearchContext:
    search_limit: int = 15
    exa_search_type: str = "auto"
    fetch_code_context: bool = False
    seed_urls: list[str] = field(default_factory=list)
    experiment_snippets: list[str] = field(default_factory=list)
    llm_config: Optional[LLMConfig] = None


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
    topic: str = Field(..., min_length=3)
    seed_urls: list[str] = Field(default_factory=list)
    experiment_snippets: list[str] = Field(default_factory=list)
    search: SearchQuery | None = None
    search_limit: int = Field(15, ge=1, le=15)
    exa_search_type: str = Field("auto")
    fetch_code_context: bool = False
    llm_config: LLMConfig | None = None
