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

    monkeypatch.setattr("app.engine.nodes.persist.artifacts_backend", lambda: backend)
    monkeypatch.setattr("app.core.settings.settings.MEMORIES_DIR", Path("memories"))
    monkeypatch.setattr("app.core.settings.settings.OUTPUT_DIR", Path("outputs"))
    return backend


def _state() -> ResearchState:
    return ResearchState(
        messages=[],
        topic="langgraph persistence",
        research_notes=["note-a", "note-b"],
        experiments=[],
        code_context=[],
        sources=[{"title": "T", "url": "https://x", "notes": "", "provider": "exa"}],
        report="",
        zettelkasten_notes=[],
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
