"""Researcher agent — investigates a topic and returns structured findings."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.engine.agents.spec import AgentSpec
from app.engine.tools import MCP_TOOLS, OPENAI_TOOLS, shell


class Source(BaseModel):
    """A single source surfaced during research.

    Field names intentionally mirror the keys consumed by
    :class:`app.engine.artifacts.CsvSourceStore` and produced by the search
    tools so structured-output sources
    round-trip to ``sources.csv`` without key translation.
    """

    id: str = Field(..., description="Citation key S1, S2, … in list order")
    title: str = Field(..., description="Title of the source")
    url: str = Field(..., description="URL of the source")
    notes: str = Field(..., description="Brief summary / notes about the content")
    score: int = Field(..., ge=1, le=10, description="Relevance score (1-10)")


class ResearcherOutput(BaseModel):
    research_notes: list[str] = Field(..., description="List of key findings and notes")
    key_insights: list[str] = Field(..., description="List of atomic insights")
    sources: list[Source] = Field(..., description="List of sources used")
    reasoning: list[str] = Field(..., description="Chain of thought reasoning")


SPEC: AgentSpec[ResearcherOutput] = AgentSpec(
    name="researcher",
    output_schema=ResearcherOutput,
    tools=(*OPENAI_TOOLS, *MCP_TOOLS, shell),
)
