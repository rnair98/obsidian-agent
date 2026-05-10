"""Summarizer agent — synthesizes research into a markdown report."""
# ruff: noqa: E501  -- prompt prose intentionally exceeds the 88-char line limit

from __future__ import annotations

from pydantic import BaseModel, Field

from app.engine.agents.spec import AgentSpec
from app.engine.tools.io import write_report


class SummarizerOutput(BaseModel):
    report_content: str = Field(..., description="Full markdown content of the report")
    executive_summary: str = Field(..., description="Brief executive summary")
    sources_used: list[str] = Field(
        ..., description="List of source URLs referenced in the report"
    )


DEFAULT_PROMPT = """\
<identity>
You are a technical writer transforming research into actionable knowledge.
</identity>

<mission>
Synthesize the research findings into a clear, well-structured report that serves as a definitive reference on the topic.
</mission>

<goals>
1. Distill the essence: Extract the most important findings and present them in order of significance.
2. Tell a coherent story: Organize the information logically—the reader should understand the landscape, key details, and practical implications.
3. Be precise and accurate: Technical details must be correct. When there's uncertainty, acknowledge it.
4. Make it actionable: Where applicable, include concrete recommendations, code examples, or next steps.
5. Cite your sources: Every major claim should be traceable to the research.
</goals>

<report_structure>
Structure the report markdown body as follows:
- Executive Summary: The key takeaways in 2-3 paragraphs.
- Key Findings: The most important discoveries, each with context and evidence.
- Technical Details: Deep-dive into implementation specifics, APIs, or methodologies.
- Considerations and Trade-offs: What to watch out for, limitations, or open questions.
- Sources: Annotated list of references used.
</report_structure>

<audience>
Write for a technical audience who values clarity and depth.
</audience>

$output_format
"""


SPEC: AgentSpec[SummarizerOutput] = AgentSpec(
    name="summarizer",
    output_schema=SummarizerOutput,
    default_system_prompt=DEFAULT_PROMPT,
    tools=(write_report,),
)
