from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Protocol, TextIO, runtime_checkable


@runtime_checkable
class FilesystemBackend(Protocol):
    base_path: Path

    def resolve(self, path: str | Path) -> Path: ...

    def exists(self, path: str | Path) -> bool: ...

    def is_file(self, path: str | Path) -> bool: ...

    def is_dir(self, path: str | Path) -> bool: ...

    def mkdir(
        self,
        path: str | Path,
        parents: bool = True,
        exist_ok: bool = True,
    ) -> Path: ...

    def list_dir(self, path: str | Path) -> list[Path]: ...

    def read_text(self, path: str | Path, encoding: str = "utf-8") -> str: ...

    def write_text(
        self,
        path: str | Path,
        content: str,
        encoding: str = "utf-8",
    ) -> Path: ...

    def read_bytes(self, path: str | Path) -> bytes: ...

    def write_bytes(self, path: str | Path, content: bytes) -> Path: ...

    def open_read(
        self,
        path: str | Path,
        mode: str = "r",
        encoding: str | None = "utf-8",
    ) -> TextIO | BinaryIO:
        """Open ``path`` for reading. ``encoding`` must be ``None`` for binary modes."""
        ...

    def open_write(
        self,
        path: str | Path,
        mode: str = "w",
        encoding: str | None = "utf-8",
    ) -> TextIO | BinaryIO:
        """Open ``path`` for writing. ``encoding`` must be ``None`` for binary modes."""
        ...

    def delete_file(self, path: str | Path, missing_ok: bool = True) -> None: ...

    def delete_dir(self, path: str | Path, missing_ok: bool = True) -> None: ...

    def move(self, src: str | Path, dst: str | Path) -> Path: ...

    def extract_tar_bytes(
        self,
        archive_bytes: bytes,
        destination: str | Path,
        strip_components: int = 1,
    ) -> Path: ...
