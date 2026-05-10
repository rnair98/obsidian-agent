"""Agent-callable IO tools.

Internal persistence helpers (``load_memories``, ``persist_memories``,
``write_sources``) live in :mod:`app.engine.persistence` — only ``@tool``
functions belong here.
"""

from __future__ import annotations

import re

from langchain.tools import tool
from pydantic import BaseModel, Field

from app.core.settings import settings
from app.engine.backends import artifacts_backend

_NOTE_ID_INVALID_RE = re.compile(r"[^A-Za-z0-9._-]+")


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


def _yaml_quote(value: str) -> str:
    """Render ``value`` as a YAML double-quoted scalar with escaping.

    YAML's double-quoted style treats ``\\`` as an escape introducer, so
    backslashes must be escaped alongside ``"``. Newlines are folded to
    spaces so a single value can't break out of the frontmatter block.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", " ").replace("\r", " ")
    return f'"{escaped}"'


def _safe_note_id(note_id: str) -> str:
    """Reduce ``note_id`` to a single safe path component.

    Collapses path separators, ``..`` traversal, and any character outside
    ``[A-Za-z0-9._-]`` so a model-emitted id can never escape the vault.
    """
    cleaned = _NOTE_ID_INVALID_RE.sub("-", note_id).strip("._-")
    return cleaned or "untitled"


def _format_zettel_note(note: ZettelNoteInput) -> str:
    """Render a note with YAML frontmatter so ``title`` and ``tags`` survive."""
    if not note.title and not note.tags:
        return note.content
    lines = ["---"]
    if note.title:
        lines.append(f"title: {_yaml_quote(note.title)}")
    if note.tags:
        rendered_tags = ", ".join(_yaml_quote(t) for t in note.tags)
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
    seen_ids: set[str] = set()
    written = 0
    for note in notes:
        base_id = _safe_note_id(note.id)
        safe_id = base_id
        suffix = 2
        # Disambiguate collisions instead of dropping notes silently.
        # Two notes with the same sanitized id (e.g. "Foo" / "foo/" both
        # collapse to "foo") now persist as ``foo.md`` and ``foo-2.md``.
        while safe_id in seen_ids:
            safe_id = f"{base_id}-{suffix}"
            suffix += 1
        seen_ids.add(safe_id)
        backend.write_text(
            vault_dir / f"{safe_id}.md",
            _format_zettel_note(note),
            encoding="utf-8",
        )
        written += 1
    return f"Saved {written} notes to {backend.resolve(vault_dir)}"
