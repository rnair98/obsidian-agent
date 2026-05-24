"""Researcher agent — investigates a topic and returns structured findings."""
# ruff: noqa: E501  -- prompt prose intentionally exceeds the 88-char line limit

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

$prior_memories

<tool_strategy>
Pick the cheapest tool that answers the question. Follow this routing
rubric — do not improvise around it:

1. Discovery (you do NOT have a URL yet):
   - `web_search` for general web discovery.
   - `exa.web_search_exa` when you want semantically-ranked results or
     long-form/technical pages.
   - `exa.get_code_context_exa` when you specifically need code snippets
     or library/API usage examples.
   - `deepwiki.ask_question` / `deepwiki.read_wiki_structure` when the
     subject is an open-source GitHub project — ask the wiki before
     scraping the repo.

2. Fetching a SPECIFIC URL you already have:
   - Use `exa.crawling_exa` to retrieve the page as clean markdown.
   - Do NOT use `shell` / `curl` for web URLs. `curl` is not a Jina
     Reader shortcut here; it just hits the network from the sandbox
     and gives you raw HTML you then have to clean up. Pages already
     surfaced by `web_search` / `web_search_exa` typically include the
     snippet you need — re-fetch only when the snippet is insufficient.

3. Calculations / quick data work:
   - Use `code_interpreter` (Python sandbox) for math, parsing, or
     validating quantitative claims. Do not use `shell python`.

4. Shell is reserved for ONE job: reading prior-memory files named in
   the manifest above via `cat /memory/<slug>`. Nothing else.
   - No `pwd`, `ls`, `ls /workspace`, `ls /memory`, `curl`, `python`,
     `find`, or other exploration. If you are tempted to "look around",
     stop — there is nothing to discover on the filesystem.

Durable artifacts (`report.md`, `notes/*.md`, `sources.csv`,
`.memories/*.md`) are written deterministically by the persist node.
Never write them via shell.
</tool_strategy>

<constraints>
You are gathering raw material. Do not synthesize a final report—that comes later.
</constraints>

$output_format
"""


SPEC: AgentSpec[ResearcherOutput] = AgentSpec(
    name="researcher",
    output_schema=ResearcherOutput,
    default_system_prompt=DEFAULT_PROMPT,
    tools=(*OPENAI_TOOLS, *MCP_TOOLS, shell),
)
