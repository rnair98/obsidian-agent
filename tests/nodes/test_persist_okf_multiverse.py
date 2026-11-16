from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from langgraph.runtime import Runtime

from app.engine.backends.inprocess import InProcessFilesystemBackend
from app.engine.nodes.persist import persist_artifacts
from app.engine.schema import ResearchContext, ResearchState, ZettelNote
from app.engine.vaults import VaultLayout
from tests.support.multiverse import Proof, World, check_always

SEED = 1
HOSTILE = 'Risky: "quoted" \\ value\n---\n# not a heading'

AXES = {
    "title": ("plain", "hostile", "missing"),
    "tags": ("none", "plain", "hostile"),
    "topic": ("plain", "hostile"),
    "note_id": ("zettel", "index", "log"),
}

CONFORMANT = Proof(
    statement=(
        "every markdown file persist writes is an OKF v0.2 concept: parseable "
        "YAML frontmatter with a non-empty type, no concept takes a reserved "
        "OKF filename, and Zettel titles, tags, and the run topic read back "
        "unchanged"
    ),
    kind="always",
    seam="persist_artifacts",
    fault_model=(
        "Agent-supplied titles, tags, topics, and note ids containing YAML "
        "syntax, quotes, backslashes, newlines, a frontmatter fence, and the "
        "reserved OKF stems index and log. Files other writers put in the "
        "vault are outside this multiverse."
    ),
    axes=tuple(AXES),
    sketch="""
1. title is a plain string, a hostile string, or absent from the note.
2. tags are absent, plain, or hostile strings.
3. topic is plain or hostile, and reaches the report and the memory file.
4. note_id is an ordinary id or one of the stems OKF §3.1 reserves.
5. persist writes the report, each Zettel, and one memory file.
6. The oracle reads each file with yaml.safe_load between the opening fence
   and the first fence line, as OKF §4 defines a concept.
Therefore every written file is conformant (OKF §11), none is named
index.md or log.md, and title, tags, and topic round-trip, for every
title, tags, topic, and note id in this multiverse.
""",
)


def test_persist_writes_okf_concepts(tmp_path: Path) -> None:
    def holds(world: World) -> None:
        root = tmp_path / f"w{world.index}"
        note = _note(world)
        _persist(root, world, note)
        written = [p for p in root.rglob("*.md") if ".obsidian" not in p.parts]
        if len(written) != 3:
            raise AssertionError(f"expected 3 markdown files, got {written}")
        for path in written:
            if path.name in {"index.md", "log.md"}:
                raise AssertionError(f"concept written to reserved {path}")
            data, _ = _concept(path.read_text())
            if not isinstance(data.get("type"), str) or not data["type"]:
                raise AssertionError(f"{path.name}: missing type in {data}")
        (zettel,) = (root / "notes").glob("*.md")
        (memory,) = (root / ".memories").glob("*.md")
        if _concept(memory.read_text())[0].get("topic") != _topic(world):
            raise AssertionError("memory topic did not round-trip")
        data, body = _concept(zettel.read_text())
        _check_generated(data)
        if "title" in note and data.get("title") != note["title"]:
            raise AssertionError(f"title {data.get('title')!r} != {note['title']!r}")
        if "tags" in note and data.get("tags") != note["tags"]:
            raise AssertionError(f"tags {data.get('tags')!r} != {note['tags']!r}")
        if note["content"] not in body:
            raise AssertionError("note content lost")
        report, report_body = _concept((root / "outputs" / "report.md").read_text())
        _check_generated(report)
        if "Useful synthesis." not in report_body:
            raise AssertionError("report content lost")

    check_always(CONFORMANT, AXES, holds, seed=SEED)


def _note(world: World) -> ZettelNote:
    note: dict[str, Any] = {"id": world.get("note_id"), "content": "One atomic idea."}
    if world.get("title") != "missing":
        note["title"] = "Plain title" if world.get("title") == "plain" else HOSTILE
    if world.get("tags") == "plain":
        note["tags"] = ["workspace", "agent"]
    elif world.get("tags") == "hostile":
        note["tags"] = ["a: b", "#hash", "x\ny"]
    return note  # type: ignore[return-value]


def _topic(world: World) -> str:
    return "plain topic" if world.get("topic") == "plain" else HOSTILE


def _persist(root: Path, world: World, note: ZettelNote) -> None:
    state = ResearchState(
        messages=[],
        topic=_topic(world),
        research_notes=["n"],
        sources=[],
        report="# Report\n\nUseful synthesis.",
        zettelkasten_notes=[note],
        reasoning=["r"],
        key_insights=["k"],
    )
    layout = VaultLayout(
        backend=InProcessFilesystemBackend(root),
        root=Path("."),
        notes_dir=Path("notes"),
        outputs_dir=Path("outputs"),
        memories_dir=Path(".memories"),
    )
    persist_artifacts(state, Runtime(context=ResearchContext(vault=layout)))


def _concept(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise AssertionError(f"no frontmatter: {text[:40]!r}")
    end = text.index("\n---\n", 4)
    data = yaml.safe_load(text[4:end])
    if not isinstance(data, dict):
        raise AssertionError(f"frontmatter is not a mapping: {data!r}")
    return data, text[end + 5 :]


def _check_generated(data: dict[str, Any]) -> None:
    generated = data.get("generated")
    if not isinstance(generated, dict) or "/" not in str(generated.get("by", "")):
        raise AssertionError(f"generated.by is not an OKF actor: {generated!r}")
    datetime.fromisoformat(str(generated.get("at")))
