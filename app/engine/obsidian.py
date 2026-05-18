from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.engine.artifacts import ArtifactWorkspaceBackend
from app.engine.backends.protocol import FilesystemBackend
from app.engine.vaults import VaultLayout
from app.harness.paths import normalize_path
from app.harness.session import WorkspaceSession

_TAG_RE = re.compile(r"(?<![\w/])#([A-Za-z0-9][A-Za-z0-9_/-]*)")
_WIKILINK_RE = re.compile(r"!?\[\[([^\]|#^]+)(?:[#^][^\]|]*)?(?:\|[^\]]*)?\]\]")
_MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


class ObsidianVaultError(ValueError):
    """Base error for optimized Obsidian vault operations."""


class NoteNotFoundError(ObsidianVaultError):
    """Raised when a file/path target cannot be resolved."""


class AmbiguousNoteError(ObsidianVaultError):
    """Raised when a wikilink-style file target matches multiple notes."""


class NoteExistsError(ObsidianVaultError):
    """Raised when create would overwrite an existing note."""


@dataclass(frozen=True, slots=True)
class SearchHit:
    path: Path
    line_number: int
    line: str


@dataclass(frozen=True, slots=True)
class NoteProperties:
    data: dict[str, Any]
    body: str


class ObsidianVaultOperations:
    """Fast headless subset of Obsidian CLI behavior over a resolved vault.

    The live Obsidian CLI is optimized for controlling a running desktop app.
    This operation layer is optimized for agent workflows that need deterministic,
    sandboxed vault reads and writes through the repository's FilesystemBackend.
    """

    def __init__(self, layout: VaultLayout) -> None:
        self.layout = layout
        self.backend = layout.backend
        self.workspace = WorkspaceSession.with_mounts(
            {
                "/vault": ArtifactWorkspaceBackend(layout.backend, layout.root),
            },
            cwd="/vault",
        )

    def list_notes(self, root: str | Path | None = None) -> list[Path]:
        scan_root = self.layout.root if root is None else Path(root)
        return [
            path
            for path in _walk_files(self.backend, scan_root)
            if path.suffix.lower() == ".md"
        ]

    def read(self, *, file: str | None = None, path: str | Path | None = None) -> str:
        return self._read_text(self.resolve_note(file=file, path=path))

    def create(
        self,
        *,
        name: str,
        content: str = "",
        folder: str | Path | None = None,
        overwrite: bool = False,
    ) -> Path:
        target = _note_create_path(name, folder=folder or self.layout.notes_dir)
        if self._is_file(target) and not overwrite:
            raise NoteExistsError(f"note already exists: {target.as_posix()}")
        self._write_text(target, content)
        return target

    def append(
        self,
        *,
        content: str,
        file: str | None = None,
        path: str | Path | None = None,
    ) -> Path:
        target = self.resolve_note(file=file, path=path)
        current = self._read_text(target)
        separator = "" if not current or current.endswith("\n") else "\n"
        self._write_text(target, f"{current}{separator}{content}")
        return target

    def search(self, query: str, *, limit: int | None = 20) -> list[SearchHit]:
        needle = query.casefold()
        hits: list[SearchHit] = []
        for path in self.list_notes():
            for line_number, line in enumerate(
                self._read_text(path).splitlines(),
                start=1,
            ):
                if needle in line.casefold():
                    hits.append(
                        SearchHit(path=path, line_number=line_number, line=line)
                    )
                    if limit is not None and len(hits) >= limit:
                        return hits
        return hits

    def tags(self) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for path in self.list_notes():
            counts.update(_TAG_RE.findall(self._read_text(path)))
        return dict(sorted(counts.items()))

    def backlinks(
        self,
        *,
        file: str | None = None,
        path: str | Path | None = None,
    ) -> list[Path]:
        target = self.resolve_note(file=file, path=path)
        target_stem = target.stem.casefold()
        target_basename = target.name.casefold()
        target_path = target.as_posix().casefold()
        linked_from: list[Path] = []
        for note_path in self.list_notes():
            if note_path == target:
                continue
            body = self._read_text(note_path)
            if _body_links_to(
                body,
                target_stem=target_stem,
                target_basename=target_basename,
                target_path=target_path,
            ):
                linked_from.append(note_path)
        return linked_from

    def properties(
        self,
        *,
        file: str | None = None,
        path: str | Path | None = None,
    ) -> NoteProperties:
        target = self.resolve_note(file=file, path=path)
        return _split_frontmatter(self._read_text(target))

    def set_property(
        self,
        name: str,
        value: Any,
        *,
        file: str | None = None,
        path: str | Path | None = None,
    ) -> Path:
        target = self.resolve_note(file=file, path=path)
        parsed = _split_frontmatter(self._read_text(target))
        data = {**parsed.data, name: value}
        self._write_text(target, _join_frontmatter(data, parsed.body))
        return target

    def resolve_note(
        self,
        *,
        file: str | None = None,
        path: str | Path | None = None,
    ) -> Path:
        if (file is None) == (path is None):
            raise ObsidianVaultError("expected exactly one of file or path")
        if path is not None:
            target = Path(path)
            if not self._is_file(target):
                raise NoteNotFoundError(f"note not found: {target.as_posix()}")
            return target
        assert file is not None
        return self._resolve_file(file)

    def _resolve_file(self, file: str) -> Path:
        target = _clean_file_target(file)
        path_like = Path(target)
        direct_candidates = [path_like]
        if path_like.suffix == "":
            direct_candidates.append(path_like.with_suffix(".md"))
        for candidate in direct_candidates:
            if self._is_file(candidate):
                return candidate

        wanted = path_like.stem.casefold() if path_like.suffix else target.casefold()
        matches = [path for path in self.list_notes() if path.stem.casefold() == wanted]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            rendered = ", ".join(path.as_posix() for path in matches)
            raise AmbiguousNoteError(f"ambiguous note target {file!r}: {rendered}")
        raise NoteNotFoundError(f"note not found: {file}")

    def _read_text(self, path: Path) -> str:
        return self.workspace.backend.read_text(_vault_workspace_path(path))

    def _write_text(self, path: Path, content: str) -> None:
        self.workspace.backend.write_text(_vault_workspace_path(path), content)

    def _is_file(self, path: Path) -> bool:
        workspace_path = _vault_workspace_path(path)
        return self.workspace.backend.exists(workspace_path) and not (
            self.workspace.backend.is_dir(workspace_path)
        )


def read_note(
    layout: VaultLayout,
    *,
    file: str | None = None,
    path: str | Path | None = None,
) -> str:
    return ObsidianVaultOperations(layout).read(file=file, path=path)


def create_note(
    layout: VaultLayout,
    *,
    name: str,
    content: str = "",
    folder: str | Path | None = None,
    overwrite: bool = False,
) -> Path:
    return ObsidianVaultOperations(layout).create(
        name=name,
        content=content,
        folder=folder,
        overwrite=overwrite,
    )


def append_note(
    layout: VaultLayout,
    *,
    content: str,
    file: str | None = None,
    path: str | Path | None = None,
) -> Path:
    return ObsidianVaultOperations(layout).append(content=content, file=file, path=path)


def search_notes(
    layout: VaultLayout,
    query: str,
    *,
    limit: int | None = 20,
) -> list[SearchHit]:
    return ObsidianVaultOperations(layout).search(query, limit=limit)


def _walk_files(backend: FilesystemBackend, root: Path) -> list[Path]:
    files: list[Path] = []
    visited: set[Path] = set()
    _walk_files_into(backend, root, files, visited)
    return sorted(files)


def _walk_files_into(
    backend: FilesystemBackend,
    root: Path,
    files: list[Path],
    visited: set[Path],
) -> None:
    for entry in backend.list_dir(root):
        relative = entry.relative_to(backend.base_path)
        if relative.parts and relative.parts[0] == ".obsidian":
            continue
        if entry.is_dir():
            # Resolve symlinks so cyclic vault trees can't trigger infinite
            # recursion. `resolve(strict=False)` returns a stable canonical
            # path even when the target does not exist.
            try:
                canonical = entry.resolve(strict=False)
            except OSError:
                continue
            if canonical in visited:
                continue
            visited.add(canonical)
            _walk_files_into(backend, relative, files, visited)
        elif entry.is_file():
            files.append(relative)


def _vault_workspace_path(path: Path) -> str:
    if path.is_absolute():
        raise ObsidianVaultError(f"vault path must be relative: {path.as_posix()}")
    workspace_path = normalize_path(f"/vault/{path.as_posix()}")
    if workspace_path != "/vault" and not workspace_path.startswith("/vault/"):
        raise ObsidianVaultError(f"vault path escapes mount: {path.as_posix()}")
    return workspace_path


def _note_create_path(name: str, *, folder: str | Path) -> Path:
    raw = Path(name)
    target = raw if raw.parent != Path(".") else Path(folder) / raw
    if target.suffix == "":
        target = target.with_suffix(".md")
    return target


def _clean_file_target(file: str) -> str:
    target = file.strip()
    if target.startswith("[[") and target.endswith("]]"):
        target = target[2:-2]
    target = target.split("|", maxsplit=1)[0]
    target = target.split("#", maxsplit=1)[0]
    target = target.split("^", maxsplit=1)[0]
    return target.strip()


def _body_links_to(
    body: str,
    *,
    target_stem: str,
    target_basename: str,
    target_path: str,
) -> bool:
    for link in _WIKILINK_RE.findall(body):
        cleaned = _clean_file_target(link).casefold()
        if cleaned == target_stem or cleaned.endswith(f"/{target_stem}"):
            return True
    for link in _MARKDOWN_LINK_RE.findall(body):
        cleaned = link.replace("%20", " ").split("#", maxsplit=1)[0].casefold()
        if cleaned == target_path or cleaned.endswith(f"/{target_path}"):
            return True
        # Relative markdown links like `(Target.md)` should also match the
        # target's basename so they aren't missed when the link doesn't
        # carry the full vault-relative path.
        if cleaned == target_basename or cleaned.endswith(f"/{target_basename}"):
            return True
    return False


def _split_frontmatter(content: str) -> NoteProperties:
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


def _join_frontmatter(data: dict[str, Any], body: str) -> str:
    rendered = yaml.safe_dump(data, sort_keys=True, allow_unicode=True).strip()
    return f"---\n{rendered}\n---\n\n{body}"
