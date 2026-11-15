from __future__ import annotations

import posixpath
from pathlib import Path

from app.engine.backends.inprocess import InProcessFilesystemBackend
from app.engine.obsidian import ObsidianVaultOperations
from app.engine.vaults import VaultLayout
from tests.support.multiverse import Proof, World, check_always

SEED = 1

AXES = {
    "form": ("wiki_bare", "wiki_path", "md_absolute", "md_relative"),
    "stem": ("b", "b.v2"),
    "other": ("same_name", "different_name"),
    "source_dir": ("notes", "topics", "inbox"),
    "aim": ("target", "other"),
}

BACKLINKS = Proof(
    statement=(
        "backlinks(target) lists a note exactly when one of its links "
        "resolves to the target, and an ambiguous bare name resolves to no note"
    ),
    kind="always",
    seam="ObsidianVaultOperations.backlinks",
    fault_model=(
        "A second note that shares the target's file name in another folder, "
        "dots inside the file name, and links written from the target's "
        "folder, the other note's folder, or a third folder. URL-encoded "
        "paths, heading anchors, embeds, and file-name case are outside "
        "this multiverse."
    ),
    axes=tuple(AXES),
    sketch="""
1. form chooses a bare wikilink, a path-qualified wikilink, an OKF
   bundle-absolute markdown link, or a markdown link relative to the
   linking note.
2. stem names the target notes/<stem>.md, with or without a dot in it.
3. other places a second note at topics/<stem>.md, sharing the target's
   file name, or at topics/c.md.
4. source_dir places the linking note in notes/, topics/, or inbox/.
5. aim chooses whether the link names the target or the other note.
6. Path-qualified forms name exactly one note, so the oracle is aim.
   A bare name shared by two notes resolves to the note in the linking
   note's folder, and to no note from a third folder (ARCHITECTURE.md §5).
Therefore the linking note appears in backlinks exactly when the oracle
says its link names the target, for every world in this multiverse.
""",
)


def test_backlinks_resolve_links_to_one_note(tmp_path: Path) -> None:
    def holds(world: World) -> None:
        target = f"notes/{world.get('stem')}.md"
        vault = _vault(tmp_path / f"w{world.index}", world, target)
        source = Path(f"{world.get('source_dir')}/src.md")
        got = source in vault.backlinks(path=target)
        expected = _expected(world)
        if got != expected:
            raise AssertionError(f"listed={got}, expected={expected}")

    check_always(BACKLINKS, AXES, holds, seed=SEED)


def _expected(world: World) -> bool:
    if world.get("form") == "wiki_bare" and world.get("other") == "same_name":
        return world.get("source_dir") == "notes"
    return world.get("aim") == "target"


def _vault(root: Path, world: World, target: str) -> ObsidianVaultOperations:
    stem = world.get("stem")
    other = f"topics/{stem}.md" if world.get("other") == "same_name" else "topics/c.md"
    source_dir = str(world.get("source_dir"))
    aimed = target if world.get("aim") == "target" else other
    link = _link(str(world.get("form")), aimed, source_dir)
    files = {
        target: "target\n",
        other: "the other note\n",
        f"{source_dir}/src.md": f"see {link}\n",
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return ObsidianVaultOperations(
        VaultLayout(
            backend=InProcessFilesystemBackend(root),
            root=Path("."),
            notes_dir=Path("notes"),
            outputs_dir=Path("outputs"),
            memories_dir=Path(".memories"),
        )
    )


def _link(form: str, aimed: str, source_dir: str) -> str:
    if form == "wiki_bare":
        return f"[[{posixpath.basename(aimed).removesuffix('.md')}]]"
    if form == "wiki_path":
        return f"[[{aimed.removesuffix('.md')}]]"
    if form == "md_absolute":
        return f"[x](/{aimed})"
    return f"[x]({posixpath.relpath(aimed, source_dir)})"
