from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.engine.backends import FilesystemBackend

_SLUG_INVALID_RE = re.compile(r"[^a-z0-9._-]+")
_SLUG_MAX_LENGTH = 80


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _yaml_double_quoted(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", " ").replace("\r", " ")
    return f'"{escaped}"'


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
        report_path_str = report_path.as_posix() if report_path else ""
        body = "\n".join(
            [
                "---",
                f"topic: {_yaml_double_quoted(topic)}",
                f"created_at: {_timestamp()}",
                "type: research_run",
                f"notes_count: {len(notes)}",
                f"source_count: {len(sources)}",
                f"insight_count: {len(insights)}",
                f"reasoning_count: {len(reasoning)}",
                f"report_path: {_yaml_double_quoted(report_path_str)}",
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
        return self.backend.write_text(memory_path, body, encoding="utf-8")
