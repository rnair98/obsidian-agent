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
from app.engine.schema import ResearchState


@pytest.fixture
def tmp_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    backend = InProcessFilesystemBackend(base_path=tmp_path)

    def fake_factory(**_kwargs):
        return backend

    monkeypatch.setattr("app.engine.nodes.persist.get_filesystem_backend", fake_factory)
    monkeypatch.setattr("app.core.settings.settings.MEMORIES_DIR", Path("memories"))
    monkeypatch.setattr("app.core.settings.settings.OUTPUT_DIR", Path("outputs"))
    return backend


def _state() -> ResearchState:
    return ResearchState(
        messages=[],
        topic="langgraph persistence",
        search_query=None,
        research_notes=["note-a", "note-b"],
        experiments=[],
        code_context=[],
        sources=[{"title": "T", "url": "https://x", "notes": "", "provider": "exa"}],
        report="",
        zettelkasten_notes=[],
        memories=[],
        reasoning=["picked exa because of code search"],
        key_insights=["langgraph state is a TypedDict"],
    )


def test_persist_writes_sources_and_memory(tmp_backend) -> None:
    result = persist_artifacts(_state())

    assert result["topic"] == "langgraph persistence"
    assert tmp_backend.is_file("outputs/sources.csv")

    frame = pl.read_csv(tmp_backend.resolve("outputs/sources.csv"))
    assert frame.height == 1
    assert frame["url"][0] == "https://x"

    memory_files = [p for p in tmp_backend.list_dir("memories") if p.suffix == ".md"]
    assert len(memory_files) == 1
    memory_body = memory_files[0].read_text()
    assert "langgraph persistence" in memory_body
    assert "langgraph state is a TypedDict" in memory_body
