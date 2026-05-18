from app.core.settings import settings
from app.engine.artifacts import CsvSourceStore, MarkdownMemoryStore
from app.engine.backends import artifacts_backend
from app.engine.schema import ResearchContext, ResearchState
from app.engine.vaults import VaultLayout


def _yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", " ").replace("\r", " ")
    return f'"{escaped}"'


def _safe_note_id(note_id: object) -> str:
    raw = str(note_id or "untitled")
    cleaned = "".join(
        character if character.isalnum() or character in "._-" else "-"
        for character in raw
    ).strip("._-")
    return cleaned or "untitled"


def _format_zettelkasten_note(note: dict[str, object]) -> str:
    title = str(note.get("title") or "")
    content = str(note.get("content") or "")
    tags = note.get("tags")
    tag_values = [str(tag) for tag in tags] if isinstance(tags, list) else []

    if not title and not tag_values:
        return content
    lines = ["---"]
    if title:
        lines.append(f"title: {_yaml_quote(title)}")
    if tag_values:
        rendered_tags = ", ".join(_yaml_quote(tag) for tag in tag_values)
        lines.append(f"tags: [{rendered_tags}]")
    lines.extend(["---", "", content])
    return "\n".join(lines)


def _materialize_zettelkasten_notes(
    state: ResearchState,
    layout: VaultLayout | None,
) -> None:
    backend = layout.backend if layout is not None else artifacts_backend()
    notes_dir = layout.notes_dir if layout is not None else settings.VAULT_DIR / "notes"
    backend.mkdir(notes_dir)
    seen_ids: set[str] = set()
    for note in state["zettelkasten_notes"]:
        base_id = _safe_note_id(note.get("id"))
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
    state: ResearchState,
    runtime: object | None = None,
    context: ResearchContext | None = None,
) -> dict:
    """Side-effect node: materialize durable run artifacts.

    Returns an empty delta — LangGraph merges this with the existing state,
    so there's no need to echo every field back through the checkpointer.
    """
    effective_context = context or getattr(runtime, "context", None)
    layout = effective_context.vault if effective_context is not None else None
    backend = layout.backend if isinstance(layout, VaultLayout) else artifacts_backend()
    report_path = (
        layout.outputs_dir / "report.md"
        if isinstance(layout, VaultLayout)
        else settings.OUTPUT_DIR / "report.md"
    )
    sources_dir = (
        layout.outputs_dir if isinstance(layout, VaultLayout) else settings.OUTPUT_DIR
    )
    memories_dir = (
        layout.memories_dir
        if isinstance(layout, VaultLayout)
        else settings.MEMORIES_DIR
    )
    backend.write_text(report_path, state["report"], encoding="utf-8")
    _materialize_zettelkasten_notes(
        state,
        layout if isinstance(layout, VaultLayout) else None,
    )
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
