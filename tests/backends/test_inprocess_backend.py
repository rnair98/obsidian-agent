from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from app.engine.backends.errors import PathEscapeError
from app.engine.backends.inprocess import InProcessFilesystemBackend


def _build_tar_with_rooted_file(path: str, content: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        data = content.encode("utf-8")
        info = tarfile.TarInfo(name=path)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_text_binary_and_listing_operations(tmp_path: Path) -> None:
    backend = InProcessFilesystemBackend(base_path=tmp_path)

    backend.write_text("notes/a.md", "hello")
    backend.write_bytes("notes/data.bin", b"xyz")

    assert backend.read_text("notes/a.md") == "hello"
    assert backend.read_bytes("notes/data.bin") == b"xyz"
    assert [p.name for p in backend.list_dir("notes")] == ["a.md", "data.bin"]


def test_move_and_delete_operations(tmp_path: Path) -> None:
    backend = InProcessFilesystemBackend(base_path=tmp_path)

    backend.write_text("a/file.txt", "content")
    moved_to = backend.move("a/file.txt", "b/file.txt")

    assert moved_to == backend.resolve("b/file.txt")
    assert backend.exists("b/file.txt")
    assert not backend.exists("a/file.txt")

    backend.delete_file("b/file.txt")
    assert not backend.exists("b/file.txt")

    backend.mkdir("tmp/dir")
    backend.delete_dir("tmp")
    assert not backend.exists("tmp")


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    backend = InProcessFilesystemBackend(base_path=tmp_path)

    with pytest.raises(PathEscapeError):
        backend.resolve("../outside.txt")


def test_extract_tar_bytes_with_strip_components(tmp_path: Path) -> None:
    backend = InProcessFilesystemBackend(base_path=tmp_path)
    archive = _build_tar_with_rooted_file("root-folder/src/main.py", "print('ok')")

    backend.extract_tar_bytes(archive, destination="snapshots/repo", strip_components=1)

    assert backend.read_text("snapshots/repo/src/main.py") == "print('ok')"
