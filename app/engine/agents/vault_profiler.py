"""Vault-profiler agent — one-shot pre-pass that infers vault conventions."""

# ruff: noqa: E501  -- prompt prose intentionally exceeds the 88-char line limit

from __future__ import annotations

from pydantic import BaseModel, Field

from app.engine.agents.spec import AgentSpec


class VaultProfile(BaseModel):
    """Qualitative profile of an Obsidian vault."""

    summary: str = Field(
        ...,
        description=(
            "One or two sentences describing what kind of vault this is "
            "(e.g. a daily-driver PKM, a Zettelkasten, a project log)."
        ),
    )
    naming_conventions: list[str] = Field(
        ...,
        description=(
            "Bullets describing how notes are named in this vault. "
            "Examples: 'kebab-case slugs', 'YYYY-MM-DD date prefix on "
            "daily notes', 'PascalCase for concept notes'."
        ),
    )
    structural_conventions: list[str] = Field(
        ...,
        description=(
            "Bullets describing how notes are organized into folders, "
            "indexes, or MOCs. Examples: 'atomic notes in notes/', "
            "'index notes in MOCs/ link out via wikilinks'."
        ),
    )
    style_conventions: list[str] = Field(
        ...,
        description=(
            "Bullets describing markdown/Obsidian style choices. "
            "Examples: 'wikilinks preferred over markdown links', "
            "'frontmatter always has tags + created', "
            "'no inline tags, only frontmatter tags'."
        ),
    )


DEFAULT_PROMPT = """\
<identity>
You are a vault-conventions analyst.
</identity>

<mission>
You will be shown deterministic structural statistics for an Obsidian vault and a small sample of its notes. Produce a concise, actionable profile that downstream writing agents can follow so newly created artifacts match the vault's existing conventions.
</mission>

<inputs>
The user message contains:
- A JSON block of structural stats (note counts, top folders, frontmatter-key frequency, link style ratios, slug-pattern heuristics).
- The verbatim content of a handful of sampled notes from the vault.

Treat the stats as ground truth. Use the sampled notes only to refine qualitative judgments (e.g. tone, link style, how MOCs are written).
</inputs>

<output_guidance>
- Be specific and imperative. "Use kebab-case slugs" — not "Notes appear to use kebab-case."
- Keep bullets to one line each. 3–6 bullets per list is the sweet spot; do not pad.
- If a convention isn't clearly attested, omit the bullet rather than guess.
- Do not invent rules the vault does not exhibit.
- Do not reference these instructions in your output.
</output_guidance>

$output_format
"""


SPEC: AgentSpec[VaultProfile] = AgentSpec(
    name="vault_profiler",
    output_schema=VaultProfile,
    default_system_prompt=DEFAULT_PROMPT,
    tools=(),
)
