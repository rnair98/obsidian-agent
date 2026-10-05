from __future__ import annotations

from pathlib import Path

from app.engine.backends.errors import PathEscapeError
from app.engine.backends.inprocess import InProcessFilesystemBackend
from tests.support.multiverse import Proof, World, check_always, check_sometimes

SEED = 1

AXES = {
    "shape": (
        "relative",
        "dot",
        "parent",
        "parents",
        "return_inside",
        "absolute_inside",
        "absolute_outside",
        "symlink",
    ),
    "operation": ("resolve", "write"),
}

CONTAINMENT = Proof(
    statement=(
        "resolve and write_text either stay inside the sandbox "
        "or raise PathEscapeError and leave every file outside it unchanged"
    ),
    kind="always",
    seam="InProcessFilesystemBackend.resolve / write_text",
    fault_model=(
        "Caller-controlled path strings and one symlink inside the sandbox "
        "that points at a sibling directory. Tar members, concurrent writers, "
        "and a base path that is itself a symlink are outside this multiverse."
    ),
    axes=tuple(AXES),
    sketch="""
1. shape selects the path: relative, dotted, parent segments, a parent
   walk that returns inside, an absolute path inside, an absolute path
   outside, or a symlink planted in the sandbox.
2. operation is either resolve or write. write_text calls resolve before
   it creates parents or writes bytes.
3. resolve expands a relative path under the sandbox and an absolute path
   on its own. Path.resolve collapses "." and ".." and follows symlinks.
4. _assert_within_base rejects the candidate unless it is relative to the
   sandbox root.
Therefore a path that still points outside after resolution does not create
a file there, and a path that resolves inside stays inside, for every shape
and every operation in this multiverse.
""",
)

ACCEPTED = Proof(
    statement="A relative write inside the sandbox is accepted at least once",
    kind="sometimes",
    seam="InProcessFilesystemBackend.write_text",
    fault_model=CONTAINMENT.fault_model,
    axes=tuple(AXES),
    sketch="""
1. shape includes a plain relative path, and operation includes write.
2. That pair is a path the containment argument says must resolve inside.
Therefore at least one world accepts a relative write. A multiverse of only
rejections would not witness this.
""",
)


def test_sandbox_contains_every_path_shape(tmp_path: Path) -> None:
    def holds(world: World) -> None:
        _exercise(tmp_path, world)

    check_always(CONTAINMENT, AXES, holds, seed=SEED)


def test_relative_write_is_sometimes_accepted(tmp_path: Path) -> None:
    def witness(world: World) -> bool:
        if world.get("shape") != "relative" or world.get("operation") != "write":
            return False
        written = _exercise(tmp_path, world)
        return written is not None and written.is_file()

    check_sometimes(ACCEPTED, AXES, witness, seed=SEED)


def _exercise(root: Path, world: World) -> Path | None:
    base = root / f"w{world.index}" / "sandbox"
    outside = root / f"w{world.index}" / "outside"
    base.mkdir(parents=True)
    outside.mkdir()
    backend = InProcessFilesystemBackend(base)
    path = _candidate(world, base, outside)
    before = _files_outside(root / f"w{world.index}", base)

    try:
        if world.get("operation") == "write":
            resolved = backend.write_text(path, "x")
        else:
            resolved = backend.resolve(path)
    except PathEscapeError:
        after = _files_outside(root / f"w{world.index}", base)
        if before != after:
            raise AssertionError("rejected path changed files outside the sandbox")
        return None

    if not _is_inside(resolved, base):
        raise AssertionError(f"returned path is outside the sandbox: {resolved}")
    after = _files_outside(root / f"w{world.index}", base)
    if before != after:
        raise AssertionError("accepted path changed files outside the sandbox")
    return resolved


def _candidate(world: World, base: Path, outside: Path) -> str:
    shape = world.get("shape")
    if shape == "relative":
        return "notes/a.md"
    if shape == "dot":
        return "notes/./a.md"
    if shape == "parent":
        return "../outside.txt"
    if shape == "parents":
        return "notes/../../outside.txt"
    if shape == "return_inside":
        return "notes/../../notes/a.md"
    if shape == "absolute_inside":
        return str(base / "notes" / "a.md")
    if shape == "absolute_outside":
        return str(outside / "outside.txt")
    if shape == "symlink":
        link = base / "escape"
        if not link.exists():
            link.symlink_to(outside, target_is_directory=True)
        return "escape/outside.txt"
    raise AssertionError(f"unknown shape {shape!r}")


def _files_outside(root: Path, base: Path) -> frozenset[Path]:
    found: set[Path] = set()
    for path in root.rglob("*"):
        if path.is_file() and not _is_inside(path, base):
            found.add(path)
    return frozenset(found)


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True
