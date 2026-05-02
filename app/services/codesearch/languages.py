from __future__ import annotations

from pathlib import Path

LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".ts": "typescript",
    ".js": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}


def detect_language(path: str | Path) -> str | None:
    """Return the tree-sitter language name for ``path`` or ``None``."""
    return LANGUAGE_BY_EXTENSION.get(Path(path).suffix.lower())
