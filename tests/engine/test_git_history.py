from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.engine.workspace_commands.git import MAX_STDOUT_BYTES, GitCommand
from app.engine.workspace_commands.python import PythonCommand
from app.harness.fs import InMemoryWorkspaceBackend
from app.harness.results import CommandResult
from app.harness.session import WorkspaceSession
from app.services.gh_client.mirror import MirrorError, ensure_mirror, run_git
from tests.support.multiverse import Proof, World, check_always, check_sometimes

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="history reads need macOS Seatbelt"
)

SEED = 1
MIRROR = "/repos/owner/repo.git"
PYTHON = "/Library/Developer/CommandLineTools/usr/bin/python3"
CANARY = "CANARY-outside-the-mirror"

LEGIT = ("log", "blame", "show")
SANDBOX_DENIED = ("blame_contents", "system_file")
AXES = {
    "probe": (
        *LEGIT,
        "diff_no_index",
        "blame_contents",
        "output_config",
        "output_outside",
        "fetch_subcommand",
        "config_subcommand",
        "global_option",
        "path_traversal",
        "relative_path",
        "output_abbreviated",
        "pager_exec",
        "pager_abbreviated",
        "system_file",
    ),
    "seam": ("shell", "monty"),
    "root": ("resolved", "symlinked"),
}

CONFINED = Proof(
    statement=(
        "an agent git command against a mirror either reads that mirror or fails, "
        "and never reveals a host file, rewrites the mirror config, or writes "
        "outside the mirror's object store"
    ),
    kind="always",
    seam="GitCommand via WorkspaceSession.run and Monty git()",
    fault_model=(
        "Agent-chosen argv after `git`, including options that read or write "
        "host paths, non-read subcommands, global options and -C path shapes. "
        "The mirror is a full local bare clone, so promisor (lazy) fetches over "
        "HTTPS are not exercised here; experiment E6 in the wiki plan covers one "
        "against github.com. Exec through a pager is covered below the argv "
        "check by test_sandbox_denies_exec_of_other_programs, host stdin by "
        "test_git_never_reads_host_stdin, and mirror liveness by the refresh "
        "tests. Short-option clusters, mirror corruption through object-store "
        "writes, disk use from lazy fetches and Monty call volume are not "
        "probed. Linux hosts are uncovered."
    ),
    axes=tuple(AXES),
    sketch="""
1. probe picks argv: three history reads, four options that name a host
   path (read or write), two non-read subcommands, a global option before
   -C, two malformed -C paths, an abbreviated --output, and a grep pager
   that names python3.
2. seam is the shell command or the Monty git() external function. Both
   call the same registered GitCommand. root is the mirror directory as a
   resolved path or through a symlink, as macOS temp and asset paths are.
3. GitCommand accepts only `-C /repos/owner/repo.git <read subcommand>`
   without --output, -O/--open-files-in-pager or --no-index, abbreviations
   included. Everything else exits 2 before a process starts.
4. Accepted argv runs under Seatbelt: reads limited to /usr/lib, /System,
   the toolchain and the mirror; writes limited to mirror/objects; exec
   limited to git and its HTTPS helper. blame_contents and system_file
   pass the argv check and fail inside Seatbelt.
Therefore no probe on either seam prints the canary, changes the mirror
config, or creates a file outside the mirror, and the history reads succeed.
""",
)

SUCCEEDS = Proof(
    statement="Monty code reads mirror history through git() at least once",
    kind="sometimes",
    seam="PythonCommand external function git()",
    fault_model=CONFINED.fault_model,
    axes=tuple(AXES),
    sketch="""
1. probe includes log, and seam includes monty, for either root.
2. That world runs `git log` from inside the Monty sandbox.
Therefore at least one world returns both fixture commits to Monty code.
""",
)


@pytest.fixture(scope="module")
def mirror_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("git-history")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(root), "GIT_CONFIG_NOSYSTEM": "1"}
    src = root / "src"
    src.mkdir()

    def git(*args: str, cwd: Path = src) -> None:
        subprocess.run(
            ["git", *args], cwd=cwd, env=env, check=True, capture_output=True
        )

    git("init", "-q", "-b", "main")
    git("config", "user.email", "a@example.invalid")
    git("config", "user.name", "a")
    (src / "f.txt").write_text("one\n")
    (src / "big.txt").write_text("x" * (MAX_STDOUT_BYTES * 2))
    git("add", ".")
    git("commit", "-qm", "first")
    (src / "f.txt").write_text("one\ntwo\n")
    git("commit", "-qam", "second")
    mirrors = root / "mirrors"
    (mirrors / "owner").mkdir(parents=True)
    git(
        "clone", "-q", "--bare", str(src), str(mirrors / "owner" / "repo.git"), cwd=root
    )
    (root / "outside").mkdir()
    (root / "outside" / "secret.txt").write_text(CANARY)
    (root / "linked").symlink_to(mirrors, target_is_directory=True)
    return root


def test_history_reads_stay_inside_the_mirror(mirror_root: Path) -> None:
    def holds(world: World) -> None:
        result, config_changed, outside_changed = _exercise(mirror_root, world)
        shown = result.stdout + result.stderr
        if CANARY in shown:
            raise AssertionError(f"host file content leaked: {shown!r}")
        if config_changed or outside_changed:
            raise AssertionError("mirror config or host files changed")
        if world.get("probe") in LEGIT and result.exit_code != 0:
            raise AssertionError(f"legitimate read failed: {result.stderr!r}")
        probe = world.get("probe")
        if probe in SANDBOX_DENIED and result.exit_code == 0:
            raise AssertionError(f"sandbox allowed a host read: {shown!r}")
        if probe not in LEGIT + SANDBOX_DENIED and result.exit_code != 2:
            raise AssertionError(f"argv check let {probe} reach git: {shown!r}")

    check_always(CONFINED, AXES, holds, seed=SEED)


def test_monty_code_reads_history(mirror_root: Path) -> None:
    def witness(world: World) -> bool:
        if world.get("probe") != "log" or world.get("seam") != "monty":
            return False
        result, _, _ = _exercise(mirror_root, world)
        return result.exit_code == 0 and result.stdout.split() == ["second", "first"]

    check_sometimes(SUCCEEDS, AXES, witness, seed=SEED)


def test_empty_result_names_its_scope(mirror_root: Path) -> None:
    result = _session(mirror_root).run(f"git -C {MIRROR} log --author=nobody")

    assert result.exit_code == 0
    assert result.stdout == ""
    assert f"git log: no output for {MIRROR}" in result.stderr


def test_large_output_is_truncated_visibly(mirror_root: Path) -> None:
    result = _session(mirror_root).run(f"git -C {MIRROR} show main:big.txt")

    assert result.exit_code == 0
    assert len(result.stdout.encode()) == MAX_STDOUT_BYTES
    assert f"truncated at {MAX_STDOUT_BYTES} of {MAX_STDOUT_BYTES * 2} bytes" in (
        result.stderr
    )


def test_missing_mirror_names_the_recovery_command(mirror_root: Path) -> None:
    result = _session(mirror_root).run("git -C /repos/owner/other.git log")

    assert result.exit_code == 1
    assert "run: git clone --bare owner/other" in result.stderr


def _session(mirror_root: Path, link: str = "mirrors") -> WorkspaceSession:
    git = GitCommand(mirror_root=mirror_root / link, token=lambda: None)
    return WorkspaceSession.with_mounts(
        {"/workspace": InMemoryWorkspaceBackend()},
        commands=[git, PythonCommand()],
    )


def _argv(probe: object, root: Path) -> list[str]:
    secret = str(root / "outside" / "secret.txt")
    config = str(root / "mirrors" / "owner" / "repo.git" / "config")
    return {
        "log": ["-C", MIRROR, "log", "--format=%s"],
        "blame": ["-C", MIRROR, "blame", "main", "--", "f.txt"],
        "show": ["-C", MIRROR, "show", "main:f.txt"],
        "diff_no_index": ["-C", MIRROR, "diff", "--no-index", secret, os.devnull],
        "blame_contents": [
            "-C",
            MIRROR,
            "blame",
            f"--contents={secret}",
            "main",
            "--",
            "f.txt",
        ],
        "output_config": ["-C", MIRROR, "log", "-1", f"--output={config}"],
        "output_outside": ["-C", MIRROR, "log", "-1", f"--output={root}/outside/w.txt"],
        "fetch_subcommand": ["-C", MIRROR, "fetch"],
        "config_subcommand": ["-C", MIRROR, "config", "core.pager", "sh"],
        "global_option": ["-c", "core.pager=sh", "-C", MIRROR, "log"],
        "path_traversal": ["-C", "/repos/../etc.git", "log"],
        "relative_path": ["-C", "owner/repo.git", "log"],
        "output_abbreviated": ["-C", MIRROR, "log", "-1", f"--outp={config}"],
        "pager_exec": ["-C", MIRROR, "grep", "--no-index", "-l", f"-O{PYTHON}", "x"],
        "pager_abbreviated": ["-C", MIRROR, "grep", f"--op={PYTHON}", "x", "main"],
        "system_file": [
            "-C",
            MIRROR,
            "blame",
            "--contents=/usr/share/dict/words",
            "main",
            "--",
            "f.txt",
        ],  # fmt: skip
    }[str(probe)]


def _exercise(root: Path, world: World) -> tuple[CommandResult, bool, bool]:
    config = root / "mirrors" / "owner" / "repo.git" / "config"
    before = (_digest(config), sorted((root / "outside").iterdir()))
    session = _session(
        root, "linked" if world.get("root") == "symlinked" else "mirrors"
    )
    argv = _argv(world.get("probe"), root)
    if world.get("seam") == "shell":
        result = session.commands["git"](session, argv)
    else:
        code = (
            f"r = git(*{argv!r})\n"
            "print(r['exit_code'])\n"
            "print(r['stderr'])\n"
            "print('---')\n"
            "print(r['stdout'])"
        )
        ran = session.commands["python"](session, ["-c", code])
        exit_line, _, rest = ran.stdout.partition("\n")
        stderr, _, stdout = rest.partition("---\n")
        result = CommandResult(
            stdout=stdout.rstrip("\n"), stderr=stderr, exit_code=int(exit_line)
        )
    after = (_digest(config), sorted((root / "outside").iterdir()))
    return result, before[0] != after[0], before[1] != after[1]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_sandbox_denies_exec_of_other_programs(mirror_root: Path) -> None:
    mirror = mirror_root / "mirrors" / "owner" / "repo.git"
    script = mirror / "objects" / "x.py"
    ran = mirror / "objects" / "ran"
    script.write_text(f"open({str(ran)!r}, 'w').write('x')\n")
    try:
        proc = run_git(
            mirror,
            ["grep", "--no-index", "-l", f"-O{PYTHON}", "open", "objects/x.py"],
            None,
            timeout=30,
        )
        assert not ran.exists(), proc.stderr
    finally:
        script.unlink()
        ran.unlink(missing_ok=True)


def test_repeat_mirror_clone_moves_branches_forward(tmp_path: Path) -> None:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1"}
    upstream = tmp_path / "upstream"
    upstream.mkdir()

    def git(*args: str, cwd: Path = upstream) -> str:
        done = subprocess.run(
            ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
        )
        return done.stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "a@example.invalid")
    git("config", "user.name", "a")
    git("config", "uploadpack.allowFilter", "true")
    git("commit", "-q", "--allow-empty", "-m", "first")
    mirror = tmp_path / "mirrors" / "repo.git"
    url = f"file://{upstream}"

    assert ensure_mirror(mirror, url, None, timeout=60).returncode == 0
    git("commit", "-q", "--allow-empty", "-m", "second")
    assert ensure_mirror(mirror, url, None, timeout=60).returncode == 0

    assert git("--git-dir", str(mirror), "rev-parse", "main") == git(
        "rev-parse", "main"
    )

    git("branch", "-m", "main", "trunk")
    assert ensure_mirror(mirror, url, None, timeout=60).returncode == 0

    assert git("--git-dir", str(mirror), "rev-parse", "HEAD") == git(
        "rev-parse", "trunk"
    )


def test_killed_clone_leaves_no_mirror(tmp_path: Path) -> None:
    mirror = tmp_path / "repo.git"
    upstream = tmp_path / "upstream"
    subprocess.run(["git", "init", "-q", "--bare", str(upstream)], check=True)

    with pytest.raises(subprocess.TimeoutExpired):
        ensure_mirror(mirror, f"file://{upstream}", None, timeout=0.001)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["upstream"]


def test_git_never_reads_host_stdin(mirror_root: Path) -> None:
    read_end, write_end = os.pipe()
    os.write(write_end, b"HOST-STDIN-CANARY\n")
    os.close(write_end)
    saved = os.dup(0)
    os.dup2(read_end, 0)
    try:
        result = _session(mirror_root).run(f"git -C {MIRROR} cat-file --batch-check")
    finally:
        os.dup2(saved, 0)
        os.close(saved)
        os.close(read_end)

    assert "HOST-STDIN-CANARY" not in result.stdout + result.stderr


def test_refresh_refuses_a_mirror_that_borrows_objects(tmp_path: Path) -> None:
    mirror = tmp_path / "repo.git"
    (mirror / "objects" / "info").mkdir(parents=True)
    (mirror / "objects" / "info" / "alternates").write_text("/elsewhere\n")

    with pytest.raises(MirrorError):
        ensure_mirror(mirror, "https://github.com/o/r.git", None, timeout=5)
