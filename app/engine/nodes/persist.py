import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.engine.agents.spec import AgentSpec
from app.engine.agents.summarizer import SPEC as SUMMARIZER_SPEC
from app.engine.agents.zettelkasten import SPEC as ZETTELKASTEN_SPEC
from app.engine.artifacts import CsvSourceStore, MarkdownMemoryStore
from app.engine.obsidian import join_frontmatter
from app.engine.schema import ResearchContext, ResearchState, SourceState, ZettelNote
from app.engine.vaults import VaultLayout, ensure_vault_layout

if TYPE_CHECKING:
    from langgraph.runtime import Runtime

_OKF_RESERVED_STEMS = frozenset({"index", "log"})
_CITATION_RE = re.compile(r"(?<!\[)\[\^?(S\d+(?:\s*[,;]\s*\^?S\d+)*)\](?![:(\]])")
_CITATION_ID_RE = re.compile(r"S\d+")


def _safe_note_id(note_id: object) -> str:
    raw = str(note_id or "untitled")
    cleaned = "".join(
        character if character.isalnum() or character in "._-" else "-"
        for character in raw
    ).strip("._-")
    if cleaned.casefold() in _OKF_RESERVED_STEMS:
        return f"{cleaned}-note"
    return cleaned or "untitled"


def _generated(spec: AgentSpec[Any], at: str) -> dict[str, str]:
    model = str(spec.llm_kwargs().get("model") or "unknown").replace("/", "-")
    return {"by": f"obsidian-agent/{model}", "at": at}


def _known_sources(sources: list[SourceState]) -> dict[str, SourceState]:
    known: dict[str, SourceState] = {}
    for source in sources:
        if source.get("id") and source.get("url"):
            known.setdefault(source["id"], source)
    return known


def _footnote_definitions(
    body: str, cited: list[str], known: dict[str, SourceState]
) -> list[str]:
    return [
        f"[^{key}]: {' '.join(known[key]['title'].split())} <{known[key]['url']}>"
        for key in cited
        if key in known and f"[^{key}]:" not in body
    ]


def _cite(
    body: str, sources: list[SourceState], *, cited_only: bool
) -> tuple[str, dict[str, Any]]:
    known = _known_sources(sources)
    cited: list[str] = []

    def footnotes(match: re.Match[str]) -> str:
        ids = _CITATION_ID_RE.findall(match.group(1))
        cited.extend(key for key in ids if key not in cited)
        return "".join(f"[^{key}]" for key in ids)

    body = _CITATION_RE.sub(footnotes, body)
    if definitions := _footnote_definitions(body, cited, known):
        body = "\n".join([body, "", *definitions])
    data = {
        "sources": [
            {"id": key, "resource": source["url"], "title": source["title"]}
            for key, source in known.items()
            if not cited_only or key in cited
        ],
        "unresolved_citations": [key for key in cited if key not in known],
    }
    return body, {key: value for key, value in data.items() if value}


def _format_zettelkasten_note(
    note: ZettelNote, sources: list[SourceState], at: str
) -> str:
    content, provenance = _cite(note.get("content", ""), sources, cited_only=True)
    data: dict[str, Any] = {
        "type": "Zettel",
        "status": "draft",
        "generated": _generated(ZETTELKASTEN_SPEC, at),
        **provenance,
    }
    if note.get("title"):
        data["title"] = note["title"]
    if note.get("tags"):
        data["tags"] = list(note["tags"])
    return join_frontmatter(data, content)


def _format_report(state: ResearchState, at: str) -> str:
    findings = "\n".join(
        [
            state["report"],
            "",
            "## Research findings (verbatim)",
            "",
            "### Key insights",
            "",
            *[f"- {insight}" for insight in state["key_insights"]],
            "",
            "### Research notes",
            "",
            *[f"- {note}" for note in state["research_notes"]],
        ]
    )
    body, provenance = _cite(findings, state["sources"], cited_only=False)
    data = {
        "type": "Research Report",
        "title": state["topic"],
        "status": "draft",
        "generated": _generated(SUMMARIZER_SPEC, at),
        **provenance,
    }
    return join_frontmatter(data, body)


def _materialize_zettelkasten_notes(
    state: ResearchState,
    layout: VaultLayout,
    at: str,
) -> None:
    backend = layout.backend
    notes_dir = layout.notes_dir
    backend.mkdir(notes_dir)
    notes = state["zettelkasten_notes"]
    file_ids = zettel_file_ids(notes)
    renames: dict[str, str] = {}
    for note, file_id in zip(notes, file_ids, strict=True):
        renames.setdefault(str(note.get("id") or ""), file_id)
    for note, file_id in zip(notes, file_ids, strict=True):
        content = note.get("content", "")
        for raw, final in renames.items():
            if raw and raw != final:
                content = content.replace(f"(/notes/{raw}.md)", f"(/notes/{final}.md)")
        backend.write_text(
            notes_dir / f"{file_id}.md",
            _format_zettelkasten_note(
                {**note, "content": content}, state["sources"], at
            ),
            encoding="utf-8",
        )


def zettel_file_ids(notes: list[ZettelNote]) -> list[str]:
    """File stem persist writes for each note; the executor reports the same."""
    file_ids: list[str] = []
    for note in notes:
        base_id = _safe_note_id(note.get("id"))
        file_id = base_id
        suffix = 2
        while file_id in file_ids:
            file_id = f"{base_id}-{suffix}"
            suffix += 1
        file_ids.append(file_id)
    return file_ids


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
    at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    backend.write_text(report_path, _format_report(state, at), encoding="utf-8")
    _materialize_zettelkasten_notes(state, layout, at)
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
