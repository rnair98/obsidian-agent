from __future__ import annotations


class PathEscapeError(ValueError):
    """Raised when a virtual path attempts to escape above ``/``."""


def normalize_path(path: str, *, cwd: str = "/") -> str:
    """Normalize a POSIX-like virtual path.

    The harness paths are not host filesystem paths. Keep this small and
    explicit so shell semantics do not accidentally leak into local IO.
    """
    raw = path.strip()
    if not raw:
        raise ValueError("path must not be empty")

    if raw.startswith("/"):
        parts = raw.split("/")
    else:
        parts = [*cwd.split("/"), *raw.split("/")]

    normalized: list[str] = []
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not normalized:
                raise PathEscapeError(f"path escapes workspace root: {path}")
            normalized.pop()
            continue
        normalized.append(part)

    return "/" + "/".join(normalized)


def parent_path(path: str) -> str:
    normalized = normalize_path(path)
    if normalized == "/":
        return "/"
    parent = normalized.rsplit("/", maxsplit=1)[0]
    return parent or "/"


def basename(path: str) -> str:
    normalized = normalize_path(path)
    if normalized == "/":
        return "/"
    return normalized.rsplit("/", maxsplit=1)[1]
