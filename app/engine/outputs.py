from pydantic import BaseModel, Field


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


class SummarizerOutput(BaseModel):
    report_content: str = Field(..., description="Full markdown content of the report")
    executive_summary: str = Field(..., description="Brief executive summary")
    sources_used: list[str] = Field(
        ..., description="List of source URLs referenced in the report"
    )


class ZettelkastenNote(BaseModel):
    id: str = Field(..., description="Unique slug/ID for the note")
    title: str = Field(..., description="Title of the atomic note")
    content: str = Field(..., description="Markdown content of the note")
    tags: list[str] = Field(..., description="List of tags")


class ZettelkastenOutput(BaseModel):
    notes: list[ZettelkastenNote] = Field(
        ..., description="List of generated atomic notes"
    )
