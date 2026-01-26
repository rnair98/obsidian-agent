import re
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
from langchain_core.tools import tool

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


def _legacy_write_report(
    output_path: Path,
    topic: str,
    notes: list[str],
    experiments: list[str],
    sources: list[dict[str, str]],
    insights: list[str],
    reasoning: list[str],
    code_context: list[str] | None = None,
) -> str:
    ensure_dir(output_path.parent)
    lines = [
        f"# Research Report: {topic}",
        "",
        "## Executive Summary",
        "",
        "This report summarizes the research findings and experiments conducted.",
        "",
        "## Research Notes",
        "",
        *[f"- {note}" for note in notes],
        "",
        "## Experiments",
        "",
        *[f"- {experiment}" for experiment in experiments],
        "",
        "## Key Insights",
        "",
        *[f"- {insight}" for insight in insights],
        "",
        "",
        "## Reasoning Log",
        "",
        *[f"- {entry}" for entry in reasoning],
        "",
        "## Sources",
        "",
        *[
            f"- {entry.get('title', 'Unknown')} ({entry.get('url', '')})"
            f" [{entry.get('provider', 'unknown')}]"
            for entry in sources
        ],
        "",
    ]
    report = "\n".join(lines)
    output_path.write_text(report, encoding="utf-8")
    return report


@tool
def write_zettelkasten_notes(notes: list[dict[str, str]]) -> str:
    """
    Save extracted Zettelkasten notes to the vault.
    Takes a list of dictionaries with 'id', 'title', 'content', 'links'.
    """
    vault_dir = settings.VAULT_DIR
    ensure_dir(vault_dir)
    # Simplified for the tool version, assuming inputs are pre-formatted
    # or we format them here.
    # For now, let's just save what we get to illustrate the pattern.
    count = 0
    for note in notes:
        p = vault_dir / f"{note.get('id', 'note')}.md"
        p.write_text(note.get("content", ""), encoding="utf-8")
        count += 1
    return f"Saved {count} notes to {vault_dir}"


def _legacy_write_zettelkasten_notes(
    vault_dir: Path,
    topic: str,
    notes: list[str],
    insights: list[str],
    report: str,
) -> list[dict[str, str]]:
    ensure_dir(vault_dir)
    created_at = timestamp()
    zettel: list[dict[str, str]] = []
    report_link = topic.lower().replace(" ", "-") + "-summary"
    for index, note in enumerate(insights or notes, start=1):
        zettel_id = f"{topic.lower().replace(' ', '-')}-{index}"
        filename = vault_dir / f"{zettel_id}.md"
        content = "\n".join(
            [
                "---",
                f'zettel_id: "{zettel_id}"',
                f'topic: "{topic}"',
                f"created_at: {created_at}",
                "links: []",
                "---",
                "",
                f"# {note[:80]}",
                "",
                note,
                "",
                f"Linked notes: [[{report_link}]]",
                "",
            ]
        )
        filename.write_text(content, encoding="utf-8")
        zettel.append({"id": zettel_id, "path": str(filename)})
    summary_path = vault_dir / f"{topic.lower().replace(' ', '-')}-summary.md"
    report_excerpt = "\n".join(report.splitlines()[:20])
    summary_content = "\n".join(
        [
            "---",
            f'topic: "{topic}"',
            f"created_at: {created_at}",
            "type: summary",
            "---",
            "",
            f"# {topic} Summary",
            "",
            "## Linked Notes",
            "",
            *[f"- [[{entry['id']}]]" for entry in zettel],
            "",
            "## Report Excerpt",
            "",
            report_excerpt,
            "",
        ]
    )
    summary_path.write_text(summary_content, encoding="utf-8")
    return zettel
