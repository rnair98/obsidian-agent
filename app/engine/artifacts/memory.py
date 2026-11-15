from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.engine.backends import FilesystemBackend
from app.engine.obsidian import join_frontmatter

_SLUG_INVALID_RE = re.compile(r"[^a-z0-9._-]+")
_SLUG_MAX_LENGTH = 80


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _slugify(topic: str) -> str:
    cleaned = _SLUG_INVALID_RE.sub("-", topic.lower().replace(" ", "-"))
    cleaned = cleaned.strip("._-")
    # Cap the slug so unbounded topic strings can't blow past the
    # filesystem's NAME_MAX when combined with the timestamp suffix.
    if len(cleaned) > _SLUG_MAX_LENGTH:
        cleaned = cleaned[:_SLUG_MAX_LENGTH].rstrip("._-")
    return cleaned or "untitled"


@dataclass(frozen=True, slots=True)
class MarkdownMemoryStore:
    backend: FilesystemBackend
    memories_dir: Path

    def write_run(
        self,
        *,
        topic: str,
        notes: list[str],
        insights: list[str],
        reasoning: list[str],
        sources: list[dict[str, str]],
        report_path: Path | None,
    ) -> Path:
        self.backend.mkdir(self.memories_dir)
        ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        memory_path = self.memories_dir / f"{_slugify(topic)}-{ts}.md"
        frontmatter = {
            "type": "research_run",
            "topic": topic,
            "created_at": _timestamp(),
            "notes_count": len(notes),
            "source_count": len(sources),
            "insight_count": len(insights),
            "reasoning_count": len(reasoning),
            "report_path": report_path.as_posix() if report_path else "",
        }
        body = "\n".join(
            [
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
        return self.backend.write_text(
            memory_path, join_frontmatter(frontmatter, body), encoding="utf-8"
        )
