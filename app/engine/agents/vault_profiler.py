"""Vault-profiler agent — one-shot pre-pass that infers vault conventions."""

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


SPEC: AgentSpec[VaultProfile] = AgentSpec(
    name="vault_profiler",
    output_schema=VaultProfile,
    tools=(),
)
