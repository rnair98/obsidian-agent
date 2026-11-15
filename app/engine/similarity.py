"""Semantic neighbours of vault notes. ARCHITECTURE.md §5 and §10."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from pathlib import Path

import httpx
import sqlite_vec

from app.engine.backends.protocol import FilesystemBackend
from app.engine.obsidian import ObsidianVaultOperations

Embed = Callable[[list[str]], list[list[float]]]

INDEX_DIR = Path(".okf-index")
# ponytail: bge-small reads 512 tokens; chunk long notes if their tails matter.
_MAX_CHARS = 1500
_BATCH = 32


def http_embedder(url: str) -> Embed:
    def embed(texts: list[str]) -> list[list[float]]:
        response = httpx.post(url, json={"input": texts}, timeout=60.0)
        response.raise_for_status()
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in data]

    return embed


class SimilarityIndex:
    """Rebuildable sqlite-vec index of note embeddings, kept outside the vault."""

    def __init__(
        self, vault: ObsidianVaultOperations, assets: FilesystemBackend, embed: Embed
    ) -> None:
        self._vault = vault
        self._embed = embed
        vault_root = vault.backend.resolve(vault.layout.root)
        key = hashlib.sha256(str(vault_root).encode()).hexdigest()[:16]
        assets.mkdir(INDEX_DIR)
        self.db_file = assets.resolve(INDEX_DIR / f"{key}.sqlite")

    def similar(
        self, text: str, *, k: int = 8, floor: float = 0.5
    ) -> list[tuple[Path, float]]:
        db = self._connect()
        try:
            self._refresh(db)
            (query,) = self._embed([text])
            if not _has_vectors(db):
                return []
            rows = db.execute(
                "SELECT notes.path, vec.distance FROM vec"
                " JOIN notes ON notes.id = vec.id"
                " WHERE vec.embedding MATCH ? AND k = ? ORDER BY vec.distance",
                (sqlite_vec.serialize_float32(query), k),
            ).fetchall()
        finally:
            db.close()
        return [(Path(p), 1.0 - d) for p, d in rows if 1.0 - d >= floor]

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_file)
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        db.execute(
            "CREATE TABLE IF NOT EXISTS notes"
            " (id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, sha TEXT NOT NULL)"
        )
        return db

    def _refresh(self, db: sqlite3.Connection) -> None:
        current = {
            path.as_posix(): self._note_text(path) for path in self._vault.list_notes()
        }
        stored = dict(db.execute("SELECT path, sha FROM notes").fetchall())
        changed = [
            (path, text, _sha(text))
            for path, text in current.items()
            if stored.get(path) != _sha(text)
        ]
        vectors = [
            vector
            for start in range(0, len(changed), _BATCH)
            for vector in self._embed(
                [text for _, text, _ in changed[start : start + _BATCH]]
            )
        ]
        with db:
            for path in stored.keys() - current.keys():
                _delete(db, path)
            for (path, _, sha), vector in zip(changed, vectors, strict=True):
                _upsert(db, path, sha, vector)

    def _note_text(self, path: Path) -> str:
        note = self._vault.properties(path=path)
        title = note.data.get("title") or path.stem
        return f"{title}. {note.body}"[:_MAX_CHARS]


def _upsert(db: sqlite3.Connection, path: str, sha: str, vector: list[float]) -> None:
    _delete(db, path)
    db.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS vec USING vec0(id INTEGER PRIMARY KEY,"
        f" embedding float[{len(vector)}] distance_metric=cosine)"
    )
    note_id = db.execute(
        "INSERT INTO notes (path, sha) VALUES (?, ?)", (path, sha)
    ).lastrowid
    db.execute(
        "INSERT INTO vec (id, embedding) VALUES (?, ?)",
        (note_id, sqlite_vec.serialize_float32(vector)),
    )


def _delete(db: sqlite3.Connection, path: str) -> None:
    row = db.execute("SELECT id FROM notes WHERE path = ?", (path,)).fetchone()
    if row is not None:
        db.execute("DELETE FROM vec WHERE id = ?", row)
        db.execute("DELETE FROM notes WHERE id = ?", row)


def _has_vectors(db: sqlite3.Connection) -> bool:
    found = db.execute("SELECT 1 FROM sqlite_master WHERE name = 'vec'").fetchone()
    return found is not None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
