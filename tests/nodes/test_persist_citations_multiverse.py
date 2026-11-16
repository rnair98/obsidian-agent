from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from langgraph.runtime import Runtime

from app.engine.backends.inprocess import InProcessFilesystemBackend
from app.engine.nodes.persist import persist_artifacts
from app.engine.schema import ResearchContext, ResearchState
from app.engine.vaults import VaultLayout
from tests.support.multiverse import Proof, World, check_always

SEED = 1
FOOTNOTE_REF = re.compile(r"\[\^(S\d+)\](?!:)")
BARE_CITATION = re.compile(r"(?<![\^\w])\[S\d+")
CITATIONS = {
    "none": ("", ""),
    "known": (" [S2]", " [^S2]"),
    "unknown": (" [S7]", " [^S7]"),
    "combined": (" [S1, S2]", " [^S1][^S2]"),
    "footnote": (" [^S1]", " [^S1]"),
}

AXES = {
    "report_cites": tuple(CITATIONS),
    "finding_cites": tuple(CITATIONS),
    "zettel_cites": tuple(CITATIONS),
    "source_ids": ("unique", "duplicate", "missing_id"),
    "s2_url": ("present", "empty"),
}

LOSSLESS = Proof(
    statement=(
        "report.md contains every research note and key insight verbatim with "
        "citations as OKF footnotes, and every cited id in the report or a "
        "Zettel resolves to a followable OKF sources entry with a footnote "
        "definition, or is listed in unresolved_citations"
    ),
    kind="always",
    seam="persist_artifacts",
    fault_model=(
        "A summary that omits findings; citations to known and unknown ids "
        "written as [S#], combined [S#, S#], or footnotes [^S#] in the summary, "
        "the findings, and a Zettel; duplicate and missing source ids; a "
        "source without a URL. Citation forms other than these and footnote "
        "definitions written by the model are outside this multiverse."
    ),
    axes=tuple(AXES),
    sketch="""
1. report_cites, finding_cites, and zettel_cites each add no citation, a
   known id, an unknown id, a combined bracket, or a footnote.
2. source_ids gives unique ids, a duplicate S1 whose first entry wins, or an
   extra source with no id, which cannot be cited.
3. s2_url leaves S2 followable or removes its URL, which makes S2 unresolved.
4. The oracle expects each finding with its citation rewritten as the
   footnote text in CITATIONS, collects footnote references with its own
   pattern, and reads the frontmatter with yaml.safe_load.
Therefore no finding is lost, no bare [S#] citation remains, and each cited
id is either a sources entry with a definition or an unresolved citation,
for every world in this multiverse.
""",
)


def test_persist_keeps_findings_and_citations(tmp_path: Path) -> None:
    def holds(world: World) -> None:
        root = tmp_path / f"w{world.index}"
        _persist(root, _state(world))
        known = _known(world)
        report, body = _concept((root / "outputs" / "report.md").read_text())
        written = CITATIONS[str(world.get("finding_cites"))][1]
        for finding in (f"finding note{written}", f"finding insight{written}"):
            if finding not in body:
                raise AssertionError(f"finding missing from report: {finding!r}")
        _check("report", report, body, known, all_sources=True)
        (zettel_path,) = (root / "notes").glob("*.md")
        zettel, zettel_body = _concept(zettel_path.read_text())
        _check("zettel", zettel, zettel_body, known, all_sources=False)

    check_always(LOSSLESS, AXES, holds, seed=SEED)


def _known(world: World) -> dict[str, str]:
    known = {"S1": "One", "S2": "Two"}
    if world.get("s2_url") == "empty":
        del known["S2"]
    return known


def _check(
    name: str,
    data: dict[str, Any],
    body: str,
    known: dict[str, str],
    *,
    all_sources: bool,
) -> None:
    if BARE_CITATION.search(body):
        raise AssertionError(f"{name} keeps a bare citation: {body!r}")
    cited = set(FOOTNOTE_REF.findall(body))
    listed = {entry["id"]: entry for entry in data.get("sources", [])}
    expected = set(known) if all_sources else cited & set(known)
    if set(listed) != expected:
        raise AssertionError(f"{name} sources {set(listed)} != {expected}")
    for key, entry in listed.items():
        if entry.get("title") != known[key] or not entry.get("resource"):
            raise AssertionError(f"{name} wrong source entry {entry}")
    if set(data.get("unresolved_citations", [])) != cited - set(known):
        raise AssertionError(f"{name} unresolved != {cited - set(known)}")
    for key in cited & set(known):
        if f"\n[^{key}]: " not in body:
            raise AssertionError(f"{name} has no footnote definition for {key}")


def _state(world: World) -> ResearchState:
    finding = CITATIONS[str(world.get("finding_cites"))][0]
    s2_url = "https://two.example" if world.get("s2_url") == "present" else ""
    sources: list[dict[str, Any]] = [
        {
            "id": "S1",
            "title": "One",
            "url": "https://one.example",
            "notes": "",
            "score": 9,
        },
        {"id": "S2", "title": "Two", "url": s2_url, "notes": "", "score": 5},
    ]
    extra = {"notes": "", "score": 1, "url": "https://extra.example"}
    if world.get("source_ids") == "duplicate":
        sources.append({"id": "S1", "title": "Dup", **extra})
    elif world.get("source_ids") == "missing_id":
        sources.append({"id": "", "title": "Anon", **extra})
    return ResearchState(
        messages=[],
        topic="citations",
        research_notes=[f"finding note{finding}"],
        sources=sources,  # type: ignore[typeddict-item]
        report="# Report\n\nShort summary."
        + CITATIONS[str(world.get("report_cites"))][0],
        zettelkasten_notes=[
            {
                "id": "z",
                "title": "Z",
                "content": "One idea." + CITATIONS[str(world.get("zettel_cites"))][0],
                "tags": [],
            }
        ],
        reasoning=["r"],
        key_insights=[f"finding insight{finding}"],
    )


def _persist(root: Path, state: ResearchState) -> None:
    layout = VaultLayout(
        backend=InProcessFilesystemBackend(root),
        root=Path("."),
        notes_dir=Path("notes"),
        outputs_dir=Path("outputs"),
        memories_dir=Path(".memories"),
    )
    persist_artifacts(state, Runtime(context=ResearchContext(vault=layout)))


def _concept(text: str) -> tuple[dict[str, Any], str]:
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end]), text[end + 5 :]
