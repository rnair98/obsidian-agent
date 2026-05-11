"""End-to-end test for the persist node.

Exercises persist_artifacts against a real (tmp_path-backed) filesystem
backend so the node's kwarg names and TypedDict access stay honest.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from app.engine.backends.inprocess import InProcessFilesystemBackend
from app.engine.nodes.persist import persist_artifacts
from app.engine.schema import ResearchContext, ResearchState
from app.engine.vaults import VaultLayout


@pytest.fixture
def tmp_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    backend = InProcessFilesystemBackend(base_path=tmp_path)

    monkeypatch.setattr("app.engine.nodes.persist.artifacts_backend", lambda: backend)
    monkeypatch.setattr("app.core.settings.settings.MEMORIES_DIR", Path("memories"))
    monkeypatch.setattr("app.core.settings.settings.OUTPUT_DIR", Path("outputs"))
    monkeypatch.setattr("app.core.settings.settings.VAULT_DIR", Path("vault"))
    return backend


def _state() -> ResearchState:
    return ResearchState(
        messages=[],
        topic="langgraph persistence",
        research_notes=["note-a", "note-b"],
        experiments=[],
        code_context=[],
        sources=[{"title": "T", "url": "https://x", "notes": "", "provider": "exa"}],
        report="# Report\n\nUseful synthesis.",
        zettelkasten_notes=[
            {
                "id": "typed-workspace",
                "title": "Typed workspace",
                "content": "The shell writes ordinary files.",
                "tags": ["workspace", "agent"],
            }
        ],
        reasoning=["picked exa because of code search"],
        key_insights=["langgraph state is a TypedDict"],
    )


def test_persist_writes_sources_and_memory(tmp_backend) -> None:
    result = persist_artifacts(_state())

    # persist_artifacts is a side-effect node — it returns an empty delta
    # so LangGraph doesn't re-checkpoint the entire state every run.
    assert result == {}
    assert tmp_backend.is_file("outputs/sources.csv")

    frame = pl.read_csv(tmp_backend.resolve("outputs/sources.csv"))
    assert frame.height == 1
    assert frame["url"][0] == "https://x"

    memory_files = [p for p in tmp_backend.list_dir("memories") if p.suffix == ".md"]
    assert len(memory_files) == 1
    memory_body = memory_files[0].read_text()
    assert "langgraph persistence" in memory_body
    assert "langgraph state is a TypedDict" in memory_body


def test_persist_materializes_report_and_zettelkasten_notes(tmp_backend) -> None:
    result = persist_artifacts(_state())

    assert result == {}
    assert tmp_backend.read_text("outputs/report.md") == "# Report\n\nUseful synthesis."
    note_body = tmp_backend.read_text("vault/typed-workspace.md")
    assert 'title: "Typed workspace"' in note_body
    assert 'tags: ["workspace", "agent"]' in note_body
    assert "The shell writes ordinary files." in note_body


def test_persist_materializes_artifacts_inside_runtime_vault(tmp_path: Path) -> None:
    backend = InProcessFilesystemBackend(base_path=tmp_path / "Vault")
    context = ResearchContext(
        vault=VaultLayout(
            backend=backend,
            root=Path("."),
            notes_dir=Path("notes"),
            outputs_dir=Path("outputs"),
            memories_dir=Path(".memories"),
        )
    )

    result = persist_artifacts(_state(), context=context)

    assert result == {}
    assert backend.read_text("outputs/report.md") == "# Report\n\nUseful synthesis."
    assert backend.is_file("outputs/sources.csv")
    assert backend.is_file("notes/typed-workspace.md")
    memory_files = [p for p in backend.list_dir(".memories") if p.suffix == ".md"]
    assert len(memory_files) == 1


def test_persist_escapes_topic_quotes_in_frontmatter(tmp_backend) -> None:
    state = _state()
    state["topic"] = 'risky "topic" with \\ backslash'

    persist_artifacts(state)

    memory_files = [p for p in tmp_backend.list_dir("memories") if p.suffix == ".md"]
    body = memory_files[0].read_text()
    assert 'topic: "risky \\"topic\\" with \\\\ backslash"' in body


def test_persist_does_not_overwrite_same_second_runs(tmp_backend) -> None:
    persist_artifacts(_state())
    persist_artifacts(_state())

    memory_files = [p for p in tmp_backend.list_dir("memories") if p.suffix == ".md"]
    assert len(memory_files) == 2
