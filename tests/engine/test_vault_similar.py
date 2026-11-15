from __future__ import annotations

import json
import math
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import pytest

from app.engine.backends.inprocess import InProcessFilesystemBackend
from app.engine.similarity import http_embedder
from app.engine.vaults import VaultLayout
from app.engine.workspace import build_workspace_session
from tests.support.multiverse import Proof, World, check_always

SEED = 1
FLOOR = 0.5
VOCAB = ("alpha", "beta", "gamma", "delta")
START = {"notes/a.md": "alpha alpha", "notes/b.md": "beta", "notes/c.md": "gamma delta"}
CHANGES = {
    "none": {},
    "edit": {"notes/b.md": "alpha alpha alpha beta"},
    "add": {"notes/d.md": "alpha delta"},
    "delete": {"notes/a.md": None},
}

AXES = {"change": tuple(CHANGES), "embedder": ("up", "down", "resized")}

SIMILAR = Proof(
    statement=(
        "vault similar TEXT lists the current vault notes whose cosine to the "
        "text is at least the floor, best first; a refused connection or a "
        "changed vector size makes it exit non-zero instead of raising; and no "
        "index file is written inside the vault"
    ),
    kind="always",
    seam="WorkspaceSession.run('vault similar ...') built by build_workspace_session",
    fault_model=(
        "A note edited, added, or deleted after the index was built; an "
        "embedding server that refuses connections; an embedding model swapped "
        "for one with a different vector size. The real model's quality, notes "
        "longer than the embedding window, and concurrent writers are outside "
        "this multiverse; E4, E4b, and E5 cover model quality."
    ),
    axes=tuple(AXES),
    sketch="""
1. The fake embedder counts the words alpha, beta, gamma, delta, so the
   oracle can compute every cosine by hand from the current file text.
2. A first query builds the index from START.
3. change then edits, adds, or deletes a note, or leaves the vault alone.
4. embedder keeps the server up, makes it refuse connections, or returns
   vectors one dimension longer than the stored ones.
5. A second query runs. The oracle ranks the current notes by cosine to
   the query and keeps those at or above the floor.
Therefore the second query prints exactly the oracle's paths in order when
the server is up, exits non-zero otherwise, and leaves the vault free of
index files, for every world.
""",
)


def test_vault_similar_tracks_the_current_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = {"mode": "up"}

    def fake_embedder(_url: str):
        def embed(texts: list[str]) -> list[list[float]]:
            if state["mode"] == "down":
                raise httpx.ConnectError("refused")
            extra = [0.5] if state["mode"] == "resized" else []
            return [_vector(text) + extra for text in texts]

        return embed

    monkeypatch.setattr(
        "app.engine.workspace_commands.vault.http_embedder", fake_embedder
    )

    def holds(world: World) -> None:
        state["mode"] = "up"
        root = tmp_path / f"w{world.index}"
        files = dict(START)
        _write(root, files)
        session = _session(root)
        session.run("vault similar alpha")
        for rel, text in CHANGES[str(world.get("change"))].items():
            files.pop(rel, None) if text is None else files.update({rel: text})
        _rewrite(root, files)
        state["mode"] = str(world.get("embedder"))
        result = session.run("vault similar alpha")
        leaked = [p for p in (root / "vault").rglob("*") if "okf-index" in p.as_posix()]
        if leaked:
            raise AssertionError(f"index written inside the vault: {leaked}")
        if state["mode"] != "up":
            if result.exit_code == 0:
                raise AssertionError(f"embedder {state['mode']} but command succeeded")
            return
        got = [line.split()[0] for line in result.stdout.splitlines()]
        if result.exit_code != 0 or got != _oracle(files):
            raise AssertionError(
                f"got {got} ({result.stderr!r}), want {_oracle(files)}"
            )

    check_always(SIMILAR, AXES, holds, seed=SEED)


def _vector(text: str) -> list[float]:
    words = text.lower().split()
    return [words.count(word) + 0.01 for word in VOCAB]


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    return dot / (math.hypot(*left) * math.hypot(*right))


def _oracle(files: dict[str, str]) -> list[str]:
    query = _vector("alpha")
    scored = [
        (_cosine(query, _vector(f"{Path(rel).stem}. {text}")), rel)
        for rel, text in files.items()
    ]
    return [
        f"/vault/{rel}" for score, rel in sorted(scored, reverse=True) if score >= FLOOR
    ]


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / "vault" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def _rewrite(root: Path, files: dict[str, str]) -> None:
    for path in (root / "vault" / "notes").glob("*.md"):
        if f"notes/{path.name}" not in files:
            path.unlink()
    _write(root, files)


def _session(root: Path):
    layout = VaultLayout(
        backend=InProcessFilesystemBackend(root / "vault"),
        root=Path("."),
        notes_dir=Path("notes"),
        outputs_dir=Path("outputs"),
        memories_dir=Path(".memories"),
    )
    return build_workspace_session(InProcessFilesystemBackend(root / "assets"), layout)


_RECORDED = (
    Path(__file__).resolve().parents[1] / "fixtures/llama_server_embeddings.json"
)


def test_http_embedder_reads_a_recorded_llama_server_reply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = json.loads(_RECORDED.read_text())
    expected = [item["embedding"] for item in recorded["data"]]
    shuffled = {**recorded, "data": list(reversed(recorded["data"]))}
    with _serve(json.dumps(shuffled).encode()) as url:
        assert http_embedder(url)(["alpha note. one idea", "beta note."]) == expected
    with _serve(b'{"error": "model not loaded"}') as url:
        monkeypatch.setattr(
            "app.engine.workspace_commands.vault.settings.EMBEDDING_URL", url
        )
        _write(tmp_path, START)
        result = _session(tmp_path).run("vault similar alpha")
    assert result.exit_code != 0
    assert "embedding server" in result.stderr


@contextmanager
def _serve(body: bytes) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1/embeddings"
    finally:
        server.shutdown()
        server.server_close()
