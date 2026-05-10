"""Filesystem persistence helpers used by nodes (not agent-callable tools).

Tool functions live in :mod:`app.engine.tools.io`; this module owns
internal helpers like ``load_memories`` / ``persist_memories`` /
``write_sources`` so the boundary between agent-facing tools and node-side
plumbing stays sharp.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from app.engine.backends import FilesystemBackend

_SLUG_INVALID_RE = re.compile(r"[^a-z0-9._-]+")


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _slugify(topic: str) -> str:
    """Render ``topic`` as a single safe filename component.

    Strips path separators, ``..`` traversal, and any character outside
    ``[a-z0-9._-]`` so the result can never escape the parent directory.
    """
    cleaned = _SLUG_INVALID_RE.sub("-", topic.lower().replace(" ", "-"))
    cleaned = cleaned.strip("._-")
    return cleaned or "untitled"


def load_memories(memories_dir: Path, backend: FilesystemBackend) -> list[str]:
    """Return the contents of every ``*.md`` file under ``memories_dir``."""
    if not backend.is_dir(memories_dir):
        return []
    return [
        backend.read_text(p, encoding="utf-8")
        for p in backend.list_dir(memories_dir)
        if p.suffix == ".md"
    ]


def persist_memories(
    memories_dir: Path,
    topic: str,
    notes: list[str],
    insights: list[str],
    reasoning: list[str],
    sources: list[dict[str, str]],
    report_path: Path | None,
    backend: FilesystemBackend,
) -> Path:
    """Write a frontmatter-rich research-run memory; return the resolved path."""
    backend.mkdir(memories_dir)
    ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    memory_path = memories_dir / f"{_slugify(topic)}-{ts}.md"
    body = "\n".join(
        [
            "---",
            f'topic: "{topic}"',
            f"created_at: {_timestamp()}",
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
    backend.write_text(memory_path, body, encoding="utf-8")
    return backend.resolve(memory_path)


def write_sources(
    sources_path: Path,
    sources: list[dict[str, str]],
    backend: FilesystemBackend,
) -> None:
    """Write ``sources`` as a Polars CSV under ``sources_path``."""
    backend.mkdir(sources_path.parent)
    frame = pl.DataFrame(
        {
            "title": [entry.get("title", "") for entry in sources],
            "url": [entry.get("url", "") for entry in sources],
            "notes": [entry.get("notes", "") for entry in sources],
            "provider": [entry.get("provider", "") for entry in sources],
            "score": [entry.get("score", "") for entry in sources],
        }
    )
    backend.write_text(sources_path, frame.write_csv(), encoding="utf-8")
