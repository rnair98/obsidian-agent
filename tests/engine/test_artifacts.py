from __future__ import annotations

from pathlib import Path

import polars as pl

from app.engine.artifacts import CsvSourceStore, MarkdownMemoryStore
from app.engine.backends.inprocess import InProcessFilesystemBackend


def test_markdown_memory_store_writes_research_run_memory(tmp_path: Path) -> None:
    backend = InProcessFilesystemBackend(base_path=tmp_path)
    store = MarkdownMemoryStore(backend, Path("memories"))

    written_path = store.write_run(
        topic='risky "topic" with \\ backslash',
        notes=["note-a"],
        insights=["insight-a"],
        reasoning=["reason-a"],
        sources=[{"title": "Source"}],
        report_path=Path("outputs/report.md"),
    )

    assert written_path.parent == backend.resolve("memories")
    assert written_path.name.startswith("risky--topic--with---backslash-")
    body = written_path.read_text()
    assert 'topic: "risky \\"topic\\" with \\\\ backslash"' in body
    assert 'report_path: "outputs/report.md"' in body
    assert "notes_count: 1" in body
    assert "source_count: 1" in body
    assert "- insight-a" in body
    assert "- reason-a" in body
    assert "- note-a" in body


def test_csv_source_store_writes_sources_csv(tmp_path: Path) -> None:
    backend = InProcessFilesystemBackend(base_path=tmp_path)
    store = CsvSourceStore(backend, Path("outputs"))

    written_path = store.write(
        [
            {
                "title": "T",
                "url": "https://x",
                "notes": "n",
                "provider": "exa",
                "score": "7",
            },
            {"url": "https://missing-fields"},
        ]
    )

    assert written_path == backend.resolve("outputs/sources.csv")
    frame = pl.read_csv(written_path)
    assert frame.columns == ["title", "url", "notes", "provider", "score"]
    assert frame["url"].to_list() == ["https://x", "https://missing-fields"]
    assert frame["title"].to_list() == ["T", ""]


def test_csv_source_store_writes_scores_of_any_shape(tmp_path: Path) -> None:
    backend = InProcessFilesystemBackend(tmp_path)
    store = CsvSourceStore(backend, Path("outputs"))
    sources = [
        {"id": "S1", "url": "https://a", "score": 7},
        {"id": "S2", "url": "https://b", "score": 0.25},
        {"id": "S3", "url": "https://c"},
        {"id": "S4", "url": "https://d", "score": None},
    ]

    written_path = store.write(sources)  # type: ignore[arg-type]

    frame = pl.read_csv(written_path, infer_schema=False)
    assert frame["score"].to_list() == ["7", "0.25", "", ""]
