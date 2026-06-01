from typing import TYPE_CHECKING

from app.engine.artifacts import CsvSourceStore, MarkdownMemoryStore
from app.engine.artifacts.memory import yaml_double_quoted
from app.engine.schema import ResearchContext, ResearchState, ZettelNote
from app.engine.vaults import VaultLayout, ensure_vault_layout

if TYPE_CHECKING:
    from langgraph.runtime import Runtime


def safe_note_id(note_id: object) -> str:
    """Sanitize an agent-supplied note id into a filesystem-safe slug.

    Public so the response projector in ``app.engine.executor`` can mirror
    persist's filename generation when reporting Zettel artifact paths.
    """
    raw = str(note_id or "untitled")
    cleaned = "".join(
        character if character.isalnum() or character in "._-" else "-"
        for character in raw
    ).strip("._-")
    return cleaned or "untitled"


# Back-compat alias for callers that imported the previous private name.
_safe_note_id = safe_note_id


def _format_zettelkasten_note(note: ZettelNote) -> str:
    title = note.get("title")
    content = note.get("content", "")
    tags = note.get("tags")

    if not title and not tags:
        return content
    lines = ["---"]
    if title:
        lines.append(f"title: {yaml_double_quoted(title)}")
    if tags:
        rendered_tags = ", ".join(yaml_double_quoted(tag) for tag in tags)
        lines.append(f"tags: [{rendered_tags}]")
    lines.extend(["---", "", content])
    return "\n".join(lines)


def _materialize_zettelkasten_notes(
    state: ResearchState,
    layout: VaultLayout,
) -> None:
    backend = layout.backend
    notes_dir = layout.notes_dir
    backend.mkdir(notes_dir)
    seen_ids: set[str] = set()
    for note in state["zettelkasten_notes"]:
        base_id = safe_note_id(note.get("id"))
        safe_id = base_id
        suffix = 2
        while safe_id in seen_ids:
            safe_id = f"{base_id}-{suffix}"
            suffix += 1
        seen_ids.add(safe_id)
        backend.write_text(
            notes_dir / f"{safe_id}.md",
            _format_zettelkasten_note(note),
            encoding="utf-8",
        )


def persist_artifacts(
    state: ResearchState, runtime: "Runtime[ResearchContext]"
) -> dict[str, object]:
    """Side-effect node: materialize durable run artifacts.

    Returns an empty delta — LangGraph merges this with the existing state,
    so there's no need to echo every field back through the checkpointer.
    """
    layout = ensure_vault_layout(runtime.context.vault)
    backend = layout.backend
    report_path = layout.outputs_dir / "report.md"
    sources_dir = layout.outputs_dir
    memories_dir = layout.memories_dir
    backend.write_text(report_path, state["report"], encoding="utf-8")
    _materialize_zettelkasten_notes(state, layout)
    CsvSourceStore(backend, sources_dir).write(state["sources"])
    MarkdownMemoryStore(backend, memories_dir).write_run(
        topic=state["topic"],
        notes=state["research_notes"],
        insights=state["key_insights"],
        reasoning=state["reasoning"],
        sources=state["sources"],
        report_path=report_path,
    )
    return {}
