"""Zettelkasten agent — extracts atomic, evergreen notes."""
# ruff: noqa: E501  -- prompt prose intentionally exceeds the 88-char line limit

from __future__ import annotations

from pydantic import BaseModel, Field

from app.engine.agents.spec import AgentSpec
from app.engine.tools import write_zettelkasten_notes


class ZettelkastenNote(BaseModel):
    id: str = Field(..., description="Unique slug/ID for the note")
    title: str = Field(..., description="Title of the atomic note")
    content: str = Field(..., description="Markdown content of the note")
    tags: list[str] = Field(..., description="List of tags")


class ZettelkastenOutput(BaseModel):
    notes: list[ZettelkastenNote] = Field(
        ..., description="List of generated atomic notes"
    )


DEFAULT_PROMPT = """\
<identity>
You are a knowledge architect building a personal knowledge base.
</identity>

<mission>
Extract atomic, evergreen insights from the research and report. Each note should stand alone as a reusable unit of knowledge.
</mission>

<goals>
1. Identify core concepts: Look for ideas, patterns, or principles that have lasting value beyond this specific research.
2. Make notes atomic: Each note should contain exactly one idea—complete enough to be understood in isolation.
3. Write for your future self: Use clear, precise language. Someone encountering this note in 6 months should immediately understand it.
4. Create connection points: Write notes in a way that invites linking to other ideas.
</goals>

<constraints>
Focus on quality over quantity. 5 excellent notes are better than 20 shallow ones.
</constraints>

$output_format
"""


SPEC: AgentSpec[ZettelkastenOutput] = AgentSpec(
    name="zettelkasten",
    output_schema=ZettelkastenOutput,
    default_system_prompt=DEFAULT_PROMPT,
    tools=(write_zettelkasten_notes,),
)
