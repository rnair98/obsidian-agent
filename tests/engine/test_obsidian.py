from __future__ import annotations

from pathlib import Path

import pytest

from app.engine.backends.inprocess import InProcessFilesystemBackend
from app.engine.obsidian import (
    AmbiguousNoteError,
    NoteExistsError,
    ObsidianVaultOperations,
    append_note,
    create_note,
    read_note,
    search_notes,
)
from app.engine.vaults import VaultLayout


@pytest.fixture
def layout(tmp_path: Path) -> VaultLayout:
    backend = InProcessFilesystemBackend(tmp_path / "Vault")
    return VaultLayout(
        backend=backend,
        root=Path("."),
        notes_dir=Path("notes"),
        outputs_dir=Path("outputs"),
        memories_dir=Path(".memories"),
    )


def test_create_read_and_append_note_use_vault_layout(layout: VaultLayout) -> None:
    created = create_note(layout, name="Agent Notes", content="# Agent Notes")

    assert created == Path("notes/Agent Notes.md")
    assert read_note(layout, file="Agent Notes") == "# Agent Notes"

    appended = append_note(layout, file="[[Agent Notes]]", content="Follow-up")

    assert appended == Path("notes/Agent Notes.md")
    assert read_note(layout, path="notes/Agent Notes.md") == (
        "# Agent Notes\nFollow-up"
    )


def test_create_note_refuses_overwrite_without_flag(layout: VaultLayout) -> None:
    create_note(layout, name="Existing", content="first")

    with pytest.raises(NoteExistsError):
        create_note(layout, name="Existing", content="second")

    create_note(layout, name="Existing", content="second", overwrite=True)

    assert read_note(layout, file="Existing") == "second"


def test_search_notes_returns_line_hits(layout: VaultLayout) -> None:
    create_note(layout, name="One", content="alpha\nneedle here")
    create_note(layout, name="Two", content="Needle there")

    hits = search_notes(layout, "needle")

    assert [(hit.path, hit.line_number, hit.line) for hit in hits] == [
        (Path("notes/One.md"), 2, "needle here"),
        (Path("notes/Two.md"), 1, "Needle there"),
    ]


def test_file_resolution_detects_ambiguous_wikilinks(layout: VaultLayout) -> None:
    create_note(layout, name="daily/Today", content="one")
    create_note(layout, name="archive/Today", content="two")

    with pytest.raises(AmbiguousNoteError):
        read_note(layout, file="Today")


def test_tags_backlinks_and_properties(layout: VaultLayout) -> None:
    vault = ObsidianVaultOperations(layout)
    create_note(
        layout,
        name="Target",
        content="---\ntitle: Target\n---\n\n#topic body",
    )
    create_note(
        layout,
        name="Source",
        content="Links to [[Target]] and #topic/subtopic",
    )

    assert vault.tags() == {"topic": 1, "topic/subtopic": 1}
    assert vault.backlinks(file="Target") == [Path("notes/Source.md")]
    assert vault.properties(file="Target").data == {"title": "Target"}

    vault.set_property("status", "done", file="Target")

    assert vault.properties(file="Target").data == {
        "status": "done",
        "title": "Target",
    }
