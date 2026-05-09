"""Backwards-compatible re-exports.

Schema definitions live next to their prompts under
``app/engine/agents/<name>.py``. This module re-exports them so older
imports continue to work; new code should import from
``app.engine.agents.<name>`` directly.
"""

from pydantic import BaseModel, Field

from app.engine.agents.summarizer import SummarizerOutput
from app.engine.agents.zettelkasten import ZettelkastenNote, ZettelkastenOutput


class Source(BaseModel):
    title: str = Field(..., description="Title of the source")
    url: str = Field(..., description="URL of the source")
    summary: str = Field(..., description="Brief summary of the content")
    relevance_score: int = Field(..., description="Relevance score (1-10)")


class ResearcherOutput(BaseModel):
    research_notes: list[str] = Field(..., description="List of key findings and notes")
    key_insights: list[str] = Field(..., description="List of atomic insights")
    sources: list[Source] = Field(..., description="List of sources used")
    reasoning: list[str] = Field(..., description="Chain of thought reasoning")


__all__ = [
    "Source",
    "ResearcherOutput",
    "SummarizerOutput",
    "ZettelkastenNote",
    "ZettelkastenOutput",
]
