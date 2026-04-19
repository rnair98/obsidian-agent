from __future__ import annotations

import io
import shutil
import tarfile
from pathlib import Path
from typing import BinaryIO, TextIO

from app.core.paths import DEFAULT_ASSETS_DIR
from app.engine.backends.errors import (
    InvalidPathError,
    OperationFailedError,
    PathEscapeError,
)


class InProcessFilesystemBackend:
    """Local filesystem backend constrained to a sandboxed base path."""

    def __init__(self, base_path: str | Path = DEFAULT_ASSETS_DIR) -> None:
        self.base_path = Path(base_path).expanduser().resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def resolve(self, path: str | Path) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (self.base_path / candidate).resolve()

        self._assert_within_base(resolved)
        return resolved

    def exists(self, path: str | Path) -> bool:
        return self.resolve(path).exists()

    def is_file(self, path: str | Path) -> bool:
        return self.resolve(path).is_file()

    def is_dir(self, path: str | Path) -> bool:
        return self.resolve(path).is_dir()

    def mkdir(
        self,
        path: str | Path,
        parents: bool = True,
        exist_ok: bool = True,
    ) -> Path:
        target = self.resolve(path)
        target.mkdir(parents=parents, exist_ok=exist_ok)
        return target

    def list_dir(self, path: str | Path) -> list[Path]:
        target = self.resolve(path)
        if not target.exists() or not target.is_dir():
            return []
        return sorted(target.iterdir())

    def read_text(self, path: str | Path, encoding: str = "utf-8") -> str:
        return self.resolve(path).read_text(encoding=encoding)

    def write_text(
        self,
        path: str | Path,
        content: str,
        encoding: str = "utf-8",
    ) -> Path:
        target = self.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding=encoding)
        return target

    def read_bytes(self, path: str | Path) -> bytes:
        return self.resolve(path).read_bytes()

    def write_bytes(self, path: str | Path, content: bytes) -> Path:
        target = self.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    def open_read(
        self,
        path: str | Path,
        mode: str = "r",
        encoding: str | None = "utf-8",
    ) -> TextIO | BinaryIO:
        target = self.resolve(path)
        if "b" in mode:
            return target.open(mode)
        return target.open(mode, encoding=encoding)

    def open_write(
        self,
        path: str | Path,
        mode: str = "w",
        encoding: str | None = "utf-8",
    ) -> TextIO | BinaryIO:
        target = self.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if "b" in mode:
            return target.open(mode)
        return target.open(mode, encoding=encoding)

    def delete_file(self, path: str | Path, missing_ok: bool = True) -> None:
        target = self.resolve(path)
        try:
            target.unlink()
        except FileNotFoundError:
            if not missing_ok:
                raise

    def delete_dir(self, path: str | Path, missing_ok: bool = True) -> None:
        target = self.resolve(path)
        if target.is_file():
            raise InvalidPathError(f"Expected directory path, got file: {target}")
        try:
            shutil.rmtree(target)
        except FileNotFoundError:
            if not missing_ok:
                raise

    def move(self, src: str | Path, dst: str | Path) -> Path:
        source = self.resolve(src)
        destination = self.resolve(dst)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # shutil.move handles cross-filesystem moves (fallback to copy+delete).
        shutil.move(source, destination)
        return destination

    def extract_tar_bytes(
        self,
        archive_bytes: bytes,
        destination: str | Path,
        strip_components: int = 1,
    ) -> Path:
        dest = self.mkdir(destination)

        try:
            with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as tar:
                for member in tar.getmembers():
                    stripped_name = self._strip_member_name(
                        member.name,
                        strip_components,
                    )
                    if stripped_name is None:
                        continue

                    resolved_member_path = (dest / stripped_name).resolve()
                    self._assert_within_base(resolved_member_path)
                    if not self._is_relative_to(resolved_member_path, dest):
                        raise PathEscapeError(
                            f"Tar member escapes destination: {member.name}"
                        )

                    member.name = stripped_name.as_posix()
                    tar.extract(member, path=dest, filter="data")
        except (tarfile.TarError, OSError) as exc:
            raise OperationFailedError(f"Unable to extract tar archive: {exc}") from exc

        return dest

    def _strip_member_name(self, name: str, strip_components: int) -> Path | None:
        member_path = Path(name)
        parts = member_path.parts
        if len(parts) <= strip_components:
            return None
        stripped = Path(*parts[strip_components:])
        if stripped.as_posix().startswith("/"):
            raise PathEscapeError(f"Absolute tar member path is not allowed: {name}")
        return stripped

    def _assert_within_base(self, candidate: Path) -> None:
        if not self._is_relative_to(candidate, self.base_path):
            raise PathEscapeError(
                f"Path '{candidate}' escapes base path '{self.base_path}'"
            )

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False
