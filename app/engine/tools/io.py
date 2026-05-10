"""Agent-callable IO tools.

Internal persistence helpers (``load_memories``, ``persist_memories``,
``write_sources``) live in :mod:`app.engine.persistence` — only ``@tool``
functions belong here.
"""

from __future__ import annotations

from langchain.tools import tool
from pydantic import BaseModel, Field

from app.core.settings import settings
from app.engine.backends import artifacts_backend


class ZettelNoteInput(BaseModel):
    """Tool-side schema for a single zettelkasten note write.

    Defined here (not imported from ``agents/zettelkasten.py``) to avoid a
    circular import: the agent module imports the tool function, and the
    tool function needs the schema at decoration time. Field names mirror
    :class:`app.engine.agents.zettelkasten.ZettelkastenNote` so the agent's
    structured output flows through unchanged.
    """

    id: str = Field(..., description="Unique slug/ID for the note")
    title: str = Field(..., description="Title of the atomic note")
    content: str = Field(..., description="Markdown content of the note")
    tags: list[str] = Field(default_factory=list, description="List of tags")


@tool(parse_docstring=True)
def save_note(note: str) -> str:
    """Record a research note or insight for later synthesis.

    Use this to capture important findings, data points, or hypotheses
    during the research phase.

    Args:
        note: Free-form markdown text of the observation or insight.

    Returns:
        A short acknowledgement string echoing the saved note.
    """
    return f"Note saved: {note}"


@tool(parse_docstring=True)
def write_report(content: str) -> str:
    """Write the final research report to ``settings.OUTPUT_DIR / report.md``.

    Args:
        content: Full markdown body of the report.

    Returns:
        A status string naming the resolved output path.
    """
    backend = artifacts_backend()
    output_path = settings.OUTPUT_DIR / "report.md"
    backend.mkdir(output_path.parent)
    written_path = backend.write_text(output_path, content, encoding="utf-8")
    return f"Report saved to {written_path}"


def _format_zettel_note(note: ZettelNoteInput) -> str:
    """Render a note with YAML frontmatter so ``title`` and ``tags`` survive."""
    if not note.title and not note.tags:
        return note.content
    lines = ["---"]
    if note.title:
        escaped = note.title.replace('"', '\\"')
        lines.append(f'title: "{escaped}"')
    if note.tags:
        escaped_tags = [t.replace('\\', '\\\\').replace('"', '\\"') for t in note.tags]
        rendered_tags = ", ".join(f'"{t}"' for t in escaped_tags)
        lines.append(f"tags: [{rendered_tags}]")
    lines.extend(["---", "", note.content])
    return "\n".join(lines)


@tool(parse_docstring=True)
def write_zettelkasten_notes(notes: list[ZettelNoteInput]) -> str:
    """Persist extracted atomic notes to ``settings.VAULT_DIR``.

    Args:
        notes: Collection of atomic notes to write. Each note is saved as
            ``{id}.md`` in the vault, with ``title``/``tags`` rendered as
            YAML frontmatter when present.

    Returns:
        A status string naming the number of notes written and the vault
        path they were saved to.
    """
    vault_dir = settings.VAULT_DIR
    backend = artifacts_backend()
    backend.mkdir(vault_dir)
    for note in notes:
        backend.write_text(
            vault_dir / f"{note.id}.md",
            _format_zettel_note(note),
            encoding="utf-8",
        )
    return f"Saved {len(notes)} notes to {backend.resolve(vault_dir)}"
