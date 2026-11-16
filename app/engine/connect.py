"""Bounded, reviewable analogy proposals. ARCHITECTURE.md §5 and §10."""

import hashlib
import random
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.engine.agents.connect import ConnectOutput
from app.engine.backends.protocol import FilesystemBackend
from app.engine.frontmatter import split_frontmatter
from app.engine.obsidian import ObsidianVaultOperations
from app.engine.similarity import Embed, SimilarityIndex
from app.engine.vaults import VaultLayout


class ConnectError(ValueError):
    pass


class ConnectUnavailable(RuntimeError):
    pass


class Source(BaseModel):
    id: str
    path: str
    title: str
    text: str
    sha256: str
    truncated: bool


class CandidatePool(BaseModel):
    notes: list[Source]
    allowed_pairs: list[tuple[str, str]]


class Evidence(BaseModel):
    path: str
    sha256: str
    quote: str


class Hypothesis(BaseModel):
    type: Literal["Hypothesis"] = "Hypothesis"
    status: Literal["draft"] = "draft"
    mechanism: str
    mapping: str
    limitation: str
    sources: tuple[Evidence, Evidence]


class ConnectReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    topic: str
    model: str | None
    status: Literal["draft", "empty"]
    source_count: int
    candidate_count: int
    truncated_sources: list[str]
    hypotheses: list[Hypothesis]


def _sources(vault: ObsidianVaultOperations) -> list[Source]:
    paths = sorted(vault.list_notes(root=vault.layout.notes_dir))
    if len(paths) > 36:
        raise ConnectError(
            "Connect supports at most 36 source notes; use a smaller test vault."
        )
    random.Random(42).shuffle(paths)
    sources = []
    for i, path in enumerate(paths):
        raw = _read_source(vault, path)
        note = split_frontmatter(raw.decode("utf-8"))
        title = str(note.data.get("title") or path.stem)
        sources.append(
            Source(
                id=f"n{i:03}",
                path=path.as_posix(),
                title=title[:200],
                text=note.body[:1500],
                sha256=_sha(raw),
                truncated=len(note.body) > 1500 or len(title) > 200,
            )
        )
    return sources


def collect_candidates(
    layout: VaultLayout, assets: FilesystemBackend, embed: Embed
) -> CandidatePool:
    vault = ObsidianVaultOperations(layout)
    sources = _sources(vault)
    if len(sources) < 2:
        return CandidatePool(notes=sources, allowed_pairs=[])
    by_path = {source.path: source.id for source in sources}
    neighbors = {source.id: set() for source in sources}
    for source in sources:
        linked = {path.as_posix() for path in vault.links(path=source.path)}
        for path in linked & by_path.keys():
            target = by_path[path]
            neighbors[source.id].add(target)
            neighbors[target].add(source.id)
    index = SimilarityIndex(vault, assets, embed, root=layout.notes_dir)
    pairs = set()
    for source in sources:
        query = f"{source.title}. {source.text}"[:1500]
        for path, _ in index.similar(query):
            target = by_path.get(path.as_posix())
            if target and _distant(source.id, target, neighbors):
                pairs.add(tuple(sorted((source.id, target))))
    return CandidatePool(notes=sources, allowed_pairs=sorted(pairs))


def _distant(a: str, b: str, neighbors: dict[str, set[str]]) -> bool:
    return a != b and b not in neighbors[a] and not (neighbors[a] & neighbors[b])


def build_report(
    run_id: str,
    topic: str,
    model: str | None,
    pool: CandidatePool,
    output: ConnectOutput,
) -> ConnectReport:
    sources = {source.id: source for source in pool.notes}
    allowed = set(pool.allowed_pairs)
    seen = set()
    hypotheses = []
    for bridge in output.bridges:
        pair = tuple(sorted((bridge.a, bridge.b)))
        if pair not in allowed or pair in seen:
            raise ConnectError(
                "Connect returned a duplicate or ineligible source pair; retry the run."
            )
        seen.add(pair)
        evidence = []
        for note_id, quote in (
            (bridge.a, bridge.evidence_a),
            (bridge.b, bridge.evidence_b),
        ):
            source = sources[note_id]
            if quote not in source.text:
                raise ConnectError(
                    "Connect returned evidence outside the excerpt; retry the run."
                )
            evidence.append(
                Evidence(path=source.path, sha256=source.sha256, quote=quote)
            )
        hypotheses.append(
            Hypothesis(
                mechanism=bridge.mechanism,
                mapping=bridge.mapping,
                limitation=bridge.limitation,
                sources=tuple(evidence),
            )
        )
    return ConnectReport(
        run_id=run_id,
        topic=topic,
        model=model,
        status="draft" if hypotheses else "empty",
        source_count=len(pool.notes),
        candidate_count=len(pool.allowed_pairs),
        truncated_sources=[source.path for source in pool.notes if source.truncated],
        hypotheses=hypotheses,
    )


def save_report(
    layout: VaultLayout, pool: CandidatePool, report: ConnectReport
) -> None:
    vault = ObsidianVaultOperations(layout)
    if set(vault.list_notes(root=layout.notes_dir)) != {
        Path(source.path) for source in pool.notes
    }:
        raise ConnectError("Source notes changed during Connect; retry the run.")
    for source in pool.notes:
        if _sha(_read_source(vault, Path(source.path))) != source.sha256:
            raise ConnectError("Source notes changed during Connect; retry the run.")
    path = layout.outputs_dir / "connect" / f"{report.run_id}.json"
    if layout.backend.exists(path):
        raise ConnectError(
            "A Connect report already exists for this run; start a new run."
        )
    layout.backend.mkdir(path.parent)
    temporary = path.with_suffix(".tmp")
    try:
        layout.backend.write_text(temporary, report.model_dump_json(indent=2) + "\n")
        layout.backend.move(temporary, path)
    finally:
        layout.backend.delete_file(temporary, missing_ok=True)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_source(vault: ObsidianVaultOperations, path: Path) -> bytes:
    with vault.backend.open_read(path, "rb", encoding=None) as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ConnectError(
            "Connect supports notes up to 64 KiB; use smaller source notes."
        )
    return raw
