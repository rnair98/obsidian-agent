from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.runtime import Runtime

from app.engine.backends.inprocess import InProcessFilesystemBackend
from app.engine.nodes.persist import persist_artifacts
from app.engine.obsidian import ObsidianVaultOperations
from app.engine.schema import ResearchContext, ResearchState
from app.engine.vaults import VaultLayout
from tests.support.multiverse import Proof, World, check_always

SEED = 1
TARGET_IDS = {
    "plain": "target-idea",
    "reserved": "index",
    "sanitized": "Odd Id!",
    "duplicate": "shared",
}

AXES = {
    "target_id": tuple(TARGET_IDS),
    "link_order": ("target_first", "linker_first"),
}

LINKS_RESOLVE = Proof(
    statement=(
        "a Zettel's /notes/<id>.md link to another note from the same run "
        "resolves to a file persist wrote, even when persist renames that "
        "note; a duplicate id resolves to the first note that has it"
    ),
    kind="always",
    seam="persist_artifacts, read back through ObsidianVaultOperations.links",
    fault_model=(
        "Target ids that persist keeps, renames because OKF reserves them, "
        "sanitizes, or suffixes as duplicates; the linking note written "
        "before or after the target. Links to notes from earlier runs and "
        "link forms other than /notes/<id>.md are outside this multiverse."
    ),
    axes=tuple(AXES),
    sketch="""
1. target_id gives the target an id that persist keeps, renames to
   index-note, sanitizes, or shares with an earlier note.
2. link_order writes the linking note before or after the target.
3. The linker's content holds [t](/notes/<raw id>.md), the id the model
   used, as the Zettelkasten prompt tells it to.
4. The oracle finds the intended note by its content marker: the target,
   or the earlier note for a duplicate id. It resolves the linker's links
   through ObsidianVaultOperations.links.
Therefore the link reaches the intended file for every world.
""",
)


def test_persisted_note_links_resolve(tmp_path: Path) -> None:
    def holds(world: World) -> None:
        root = tmp_path / f"w{world.index}"
        raw = TARGET_IDS[str(world.get("target_id"))]
        vault = _persist(root, raw, str(world.get("link_order")))
        intended = "FIRST" if world.get("target_id") == "duplicate" else "TARGET"
        (linker,) = _notes_containing(root, "LINKER")
        (expected,) = _notes_containing(root, intended)
        if vault.links(path=linker) != [expected]:
            raise AssertionError(
                f"{linker} links to {vault.links(path=linker)}, expected {expected}"
            )

    check_always(LINKS_RESOLVE, AXES, holds, seed=SEED)


def _notes_containing(root: Path, marker: str) -> list[Path]:
    return [
        path.relative_to(root)
        for path in (root / "notes").glob("*.md")
        if marker in path.read_text()
    ]


def _persist(root: Path, raw: str, order: str) -> ObsidianVaultOperations:
    target = _note(raw, "TARGET")
    linker = _note("linker", f"LINKER [t](/notes/{raw}.md)")
    notes = [target, linker] if order == "target_first" else [linker, target]
    if raw == "shared":
        notes.insert(0, _note("shared", "FIRST"))
    state = ResearchState(
        messages=[],
        topic="links",
        research_notes=[],
        sources=[],
        report="r",
        zettelkasten_notes=notes,  # type: ignore[typeddict-item]
        reasoning=[],
        key_insights=[],
    )
    layout = VaultLayout(
        backend=InProcessFilesystemBackend(root),
        root=Path("."),
        notes_dir=Path("notes"),
        outputs_dir=Path("outputs"),
        memories_dir=Path(".memories"),
    )
    persist_artifacts(state, Runtime(context=ResearchContext(vault=layout)))
    return ObsidianVaultOperations(layout)


def _note(note_id: str, content: str) -> dict[str, Any]:
    return {"id": note_id, "title": note_id, "content": content, "tags": []}
