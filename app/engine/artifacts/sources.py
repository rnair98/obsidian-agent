from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from app.engine.backends import FilesystemBackend


@dataclass(frozen=True, slots=True)
class CsvSourceStore:
    backend: FilesystemBackend
    output_dir: Path

    def write(
        self,
        sources: list[dict[str, str]],
        *,
        filename: str = "sources.csv",
    ) -> Path:
        sources_path = self.output_dir / filename
        self.backend.mkdir(sources_path.parent)
        frame = pl.DataFrame(
            {
                "title": [entry.get("title", "") for entry in sources],
                "url": [entry.get("url", "") for entry in sources],
                "notes": [entry.get("notes", "") for entry in sources],
                "provider": [entry.get("provider", "") for entry in sources],
                "score": [entry.get("score", "") for entry in sources],
            }
        )
        return self.backend.write_text(
            sources_path,
            frame.write_csv(),
            encoding="utf-8",
        )
