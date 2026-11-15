"""Summarizer agent — synthesizes research into a markdown report."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.engine.agents.spec import AgentSpec


class SummarizerOutput(BaseModel):
    report_content: str = Field(..., description="Full markdown content of the report")
    executive_summary: str = Field(..., description="Brief executive summary")
    sources_used: list[str] = Field(
        ..., description="List of source URLs referenced in the report"
    )


SPEC: AgentSpec[SummarizerOutput] = AgentSpec(
    name="summarizer",
    output_schema=SummarizerOutput,
    tools=(),
)
