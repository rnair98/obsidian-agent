"""Zettelkasten agent — extracts atomic, evergreen notes."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.engine.agents.spec import AgentSpec
from app.engine.tools import shell


class ZettelkastenNote(BaseModel):
    id: str = Field(..., description="Unique slug/ID for the note")
    title: str = Field(..., description="Title of the atomic note")
    content: str = Field(..., description="Markdown content of the note")
    tags: list[str] = Field(..., description="List of tags")


class ZettelkastenOutput(BaseModel):
    notes: list[ZettelkastenNote] = Field(
        ..., description="List of generated atomic notes"
    )


SPEC: AgentSpec[ZettelkastenOutput] = AgentSpec(
    name="zettelkasten",
    output_schema=ZettelkastenOutput,
    tools=(shell,),
)
