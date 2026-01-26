import re
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.settings import settings


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_memories(memories_dir: Path) -> list[str]:
    if not memories_dir.exists():
        return []
    memories: list[str] = []
    for memory in sorted(memories_dir.glob("*.md")):
        memories.append(memory.read_text(encoding="utf-8"))
    return memories


def extract_memory_insights(memories: list[str]) -> list[str]:
    insights: list[str] = []
    for memory in memories:
        section_match = re.split(r"^# Key Insights\s*$", memory, flags=re.MULTILINE)
        if len(section_match) < 2:
            continue
        section = section_match[1]
        for line in section.splitlines():
            if line.startswith("- "):
                insights.append(line[2:].strip())
    return insights


def persist_memories(
    memories_dir: Path,
    topic: str,
    notes: list[str],
    insights: list[str],
    reasoning: list[str],
    sources: list[dict[str, str]],
    report_path: Path | None,
) -> list[Path]:
    ensure_dir(memories_dir)
    slug = topic.lower().replace(" ", "-")
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    memory_path = memories_dir / f"{slug}-{timestamp}.md"
    content = "\n".join(
        [
            "---",
            f'topic: "{topic}"',
            f"created_at: {timestamp()}",
            "type: research_run",
            f"notes_count: {len(notes)}",
            f"source_count: {len(sources)}",
            f"insight_count: {len(insights)}",
            f"reasoning_count: {len(reasoning)}",
            f'report_path: "{report_path.as_posix() if report_path else ""}"',
            "---",
            "",
            "# Key Insights",
            "",
            *[f"- {insight}" for insight in insights],
            "",
            "# Reasoning Log",
            "",
            *[f"- {entry}" for entry in reasoning],
            "",
            "# Research Notes",
            "",
            *[f"- {note}" for note in notes],
            "",
        ]
    )
    memory_path.write_text(content, encoding="utf-8")
    return [memory_path]


def write_sources(sources_path: Path, sources: list[dict[str, str]]) -> None:
    ensure_dir(sources_path.parent)
    frame = pl.DataFrame(
        {
            "title": [entry.get("title", "") for entry in sources],
            "url": [entry.get("url", "") for entry in sources],
            "notes": [entry.get("notes", "") for entry in sources],
            "provider": [entry.get("provider", "") for entry in sources],
            "score": [entry.get("score", "") for entry in sources],
        }
    )
    frame.write_csv(sources_path)


@tool
def save_note(note: str) -> str:
    """
    Save a research note or insight to the shared state.
    Use this to record important findings, data points, or hypotheses.
    """
    return f"Note saved: {note}"


@tool
def write_report(content: str) -> str:
    """
    Write the final research report to the disk.
    The content should be a complete markdown string.
    """
    output_path = settings.OUTPUT_DIR / "report.md"
    ensure_dir(output_path.parent)
    output_path.write_text(content, encoding="utf-8")
    return f"Report saved to {output_path}"


class ZettelNote(BaseModel):
    id: str = Field(..., description="Unique identifier for the note (slug format)")
    title: str = Field(..., description="Title of the note")
    content: str = Field(..., description="Markdown content of the note")
    links: list[str] = Field(
        default_factory=list, description="List of linked note IDs"
    )


@tool
def write_zettelkasten_notes(notes: list[ZettelNote]) -> str:
    """
    Save extracted Zettelkasten notes to the vault.
    """
    vault_dir = settings.VAULT_DIR
    ensure_dir(vault_dir)
    # Simplified for the tool version, assuming inputs are pre-formatted
    # or we format them here.
    count = 0
    for note in notes:
        # note is now a ZettelNote object
        p = vault_dir / f"{note.id}.md"
        p.write_text(note.content, encoding="utf-8")
        count += 1
    return f"Saved {count} notes to {vault_dir}"
