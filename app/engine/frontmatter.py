"""YAML frontmatter for OKF concepts. A leaf module: it imports no engine code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class NoteProperties:
    data: dict[str, Any]
    body: str


def split_frontmatter(content: str) -> NoteProperties:
    if not content.startswith("---\n"):
        return NoteProperties(data={}, body=content)
    end = content.find("\n---\n", 4)
    if end == -1:
        return NoteProperties(data={}, body=content)
    raw = content[4:end]
    body = content[end + 5 :]
    if body.startswith("\n"):
        body = body[1:]
    loaded = yaml.safe_load(raw) if raw.strip() else {}
    data = loaded if isinstance(loaded, dict) else {}
    return NoteProperties(data=data, body=body)


def join_frontmatter(data: dict[str, Any], body: str) -> str:
    rendered = yaml.safe_dump(data, sort_keys=True, allow_unicode=True).strip()
    return f"---\n{rendered}\n---\n\n{body}"
