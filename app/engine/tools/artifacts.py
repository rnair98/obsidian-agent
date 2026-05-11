from __future__ import annotations

import re

from langchain.tools import tool
from pydantic import BaseModel, Field

from app.core.settings import settings
from app.engine.backends import artifacts_backend

_NOTE_ID_INVALID_RE = re.compile(r"[^A-Za-z0-9._-]+")


class ZettelNoteInput(BaseModel):
    """Tool-side schema for a single zettelkasten note write."""

    id: str = Field(..., description="Unique slug/ID for the note")
    title: str = Field(..., description="Title of the atomic note")
    content: str = Field(..., description="Markdown content of the note")
    tags: list[str] = Field(default_factory=list, description="List of tags")


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
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", " ").replace("\r", " ")
    return f'"{escaped}"'


def _safe_note_id(note_id: str) -> str:
    cleaned = _NOTE_ID_INVALID_RE.sub("-", note_id).strip("._-")
    return cleaned or "untitled"


def _format_zettel_note(note: ZettelNoteInput) -> str:
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
