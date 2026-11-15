from __future__ import annotations

from pathlib import Path

from app.engine.backends.inprocess import InProcessFilesystemBackend
from app.engine.vaults import VaultLayout
from app.engine.workspace import build_workspace_session
from app.harness.session import WorkspaceSession
from tests.support.multiverse import Proof, World, check_always

SEED = 1
FILES = {
    "notes/a.md": "---\ntype: Zettel\n---\nSee [b](/notes/b.md) and [[c]].\n",
    "notes/b.md": "---\ntype: Zettel\n---\nBack to [a](../notes/a.md).\n",
    "notes/c.md": "---\ntype: Zettel\n---\nTagged #graph idea.\n",
    "topics/d.md": "---\ntype: Zettel\n---\nA needle in prose.\n",
}
EXPECTED = {
    "links": "/vault/notes/b.md\n/vault/notes/c.md\n",
    "backlinks": "/vault/notes/b.md\n",
}

AXES = {
    "subcommand": ("links", "backlinks", "search", "tags", "flag", "unknown"),
    "note": ("vault_relative", "absolute", "bare_name", "missing"),
}

VAULT_COMMAND = Proof(
    statement=(
        "the vault command prints the graph the vault files define, as /vault "
        "paths, and rejects a missing note, a flag, or an unknown subcommand "
        "with a non-zero exit instead of raising"
    ),
    kind="always",
    seam="WorkspaceSession.run('vault ...') built by build_workspace_session",
    fault_model=(
        "Notes named by vault-relative path, /vault path, or bare name; a note "
        "that does not exist; a flag; an unknown subcommand. Concurrent writers "
        "and vaults too large to scan per call are outside this multiverse."
    ),
    axes=tuple(AXES),
    sketch="""
1. The fixture links a to b by an OKF vault-root link and to c by a bare
   wikilink; b links back to a by a relative link; c carries #graph; d holds
   the word needle.
2. subcommand selects links, backlinks, search, tags, a flag, or an unknown
   subcommand. note names a as notes/a.md, /vault/notes/a.md, or a, or names
   a note that does not exist.
3. The oracle is EXPECTED for links and backlinks of a, the d line for
   search needle, #graph for tags, and exit code 2 or 1 for rejections.
Therefore every world either prints the fixture's graph or fails with a
non-zero exit, and none raises.
""",
)


def test_vault_command_prints_the_graph(tmp_path: Path) -> None:
    def holds(world: World) -> None:
        session = _session(tmp_path / f"w{world.index}")
        subcommand = str(world.get("subcommand"))
        note = _note_arg(str(world.get("note")))
        result = session.run(_command(subcommand, note))
        _check(subcommand, str(world.get("note")), result.exit_code, result.stdout)

    check_always(VAULT_COMMAND, AXES, holds, seed=SEED)


def _check(subcommand: str, note: str, exit_code: int, stdout: str) -> None:
    if subcommand in ("flag", "unknown"):
        if exit_code != 2:
            raise AssertionError(f"{subcommand}: exit {exit_code}, expected 2")
        return
    if subcommand in EXPECTED and note == "missing":
        if exit_code == 0:
            raise AssertionError("missing note was accepted")
        return
    expected = {
        **EXPECTED,
        "search": "/vault/topics/d.md:4: A needle in prose.\n",
        "tags": "#graph 1\n",
    }[subcommand]
    if exit_code != 0 or stdout != expected:
        raise AssertionError(f"{subcommand}: exit {exit_code}, stdout {stdout!r}")


def _command(subcommand: str, note: str) -> str:
    return {
        "links": f"vault links {note}",
        "backlinks": f"vault backlinks {note}",
        "search": "vault search needle",
        "tags": "vault tags",
        "flag": f"vault links -r {note}",
        "unknown": "vault rewrite everything",
    }[subcommand]


def _note_arg(form: str) -> str:
    return {
        "vault_relative": "notes/a.md",
        "absolute": "/vault/notes/a.md",
        "bare_name": "a",
        "missing": "notes/zzz.md",
    }[form]


def _session(root: Path) -> WorkspaceSession:
    for rel, text in FILES.items():
        path = root / "vault" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    layout = VaultLayout(
        backend=InProcessFilesystemBackend(root / "vault"),
        root=Path("."),
        notes_dir=Path("notes"),
        outputs_dir=Path("outputs"),
        memories_dir=Path(".memories"),
    )
    return build_workspace_session(InProcessFilesystemBackend(root / "assets"), layout)
