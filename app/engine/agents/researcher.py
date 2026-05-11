"""Researcher agent — investigates a topic and returns structured findings."""
# ruff: noqa: E501  -- prompt prose intentionally exceeds the 88-char line limit

from __future__ import annotations

from pydantic import BaseModel, Field

from app.engine.agents.spec import AgentSpec
from app.engine.tools import MCP_TOOLS, OPENAI_TOOLS
from app.engine.tools.shell import shell
from app.engine.tools.web import fetch_url


class Source(BaseModel):
    """A single source surfaced during research.

    Field names intentionally mirror the keys consumed by
    :func:`app.engine.persistence.write_sources` and produced by the
    search tools in :mod:`app.engine.tools.search` so structured-output
    sources round-trip to ``sources.csv`` without key translation.
    """

    title: str = Field(..., description="Title of the source")
    url: str = Field(..., description="URL of the source")
    notes: str = Field(..., description="Brief summary / notes about the content")
    score: int = Field(..., ge=1, le=10, description="Relevance score (1-10)")


class ResearcherOutput(BaseModel):
    research_notes: list[str] = Field(..., description="List of key findings and notes")
    key_insights: list[str] = Field(..., description="List of atomic insights")
    sources: list[Source] = Field(..., description="List of sources used")
    reasoning: list[str] = Field(..., description="Chain of thought reasoning")


DEFAULT_PROMPT = """\
<identity>
You are an expert technical researcher.
</identity>

<mission>
Conduct thorough, multi-perspective research on the user's topic. Your output will directly inform the final report, so prioritize depth over breadth and accuracy over speed.
</mission>

<goals>
1. Understand the landscape: Map out the key concepts, players, and debates in this space. Identify what's settled knowledge vs. active areas of disagreement.
2. Find authoritative sources: Prioritize primary sources, official documentation, peer-reviewed research, and expert commentary. Cross-reference claims across multiple sources.
3. Capture technical details: When relevant, gather code examples, API signatures, configuration patterns, or implementation specifics that would be useful for practitioners.
4. Verify claims: If you encounter quantitative claims or technical assertions, validate them where possible. Run experiments or calculations to confirm understanding.
5. Document your findings: Record important discoveries as you go, including the source and why it matters.
</goals>

<mindset>
- Be skeptical of single sources; triangulate important claims.
- Note contradictions or gaps in available information.
- Think like a journalist: who, what, when, where, why, and how.
- Stop when you have enough material to write a comprehensive report, not before.
</mindset>

<prior_memories>
Durable prior research runs are available as markdown files under
`/memory`. Treat these as privileged context: use `ls`, `grep`, and `cat`
to inspect relevant history, extract Key Insights, note what was already
settled, and avoid re-deriving conclusions that have already been captured.
If no relevant memories are present, begin fresh without comment.
</prior_memories>

<workspace>
Use the shell tool for Unix-style memory archaeology and scratch notes.
During research, create any ad hoc notes as ordinary files under
`/workspace` rather than using a special note-taking tool.
</workspace>

<constraints>
You are gathering raw material. Do not synthesize a final report—that comes later.
</constraints>

$output_format
"""


SPEC: AgentSpec[ResearcherOutput] = AgentSpec(
    name="researcher",
    output_schema=ResearcherOutput,
    default_system_prompt=DEFAULT_PROMPT,
    tools=(*OPENAI_TOOLS, *MCP_TOOLS, fetch_url, shell),
)
