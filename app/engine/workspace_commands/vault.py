from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from app.engine.obsidian import ObsidianVaultOperations
from app.engine.vaults import VaultLayout
from app.harness.commands import CommandSpec, first_flag, unsupported_flag
from app.harness.results import CommandResult
from app.harness.session import WorkspaceSession

_MOUNT = "/vault/"


class VaultCommand:
    """Read the vault's note graph: search, outgoing links, backlinks, tags."""

    spec = CommandSpec(
        name="vault",
        forms=(
            "vault search QUERY",
            "vault links NOTE",
            "vault backlinks NOTE",
            "vault tags",
        ),
    )

    def __init__(self, layout: VaultLayout) -> None:
        self._vault = ObsidianVaultOperations(layout)

    def __call__(self, _session: WorkspaceSession, args: list[str]) -> CommandResult:
        if flag := first_flag(args):
            return unsupported_flag(self.spec, flag)
        match args:
            case ["search", query]:
                return _ok(
                    f"{_MOUNT}{hit.path.as_posix()}:{hit.line_number}: {hit.line}"
                    for hit in self._vault.search(query, limit=50)
                )
            case ["links", note]:
                return _paths(self._vault.links(**_note(note)))
            case ["backlinks", note]:
                return _paths(self._vault.backlinks(**_note(note)))
            case ["tags"]:
                return _ok(
                    f"#{tag} {count}" for tag, count in self._vault.tags().items()
                )
            case _:
                forms = "\n".join(self.spec.forms)
                return CommandResult.error(
                    f"vault: expected one of\n{forms}\n", exit_code=2
                )


def _note(note: str) -> dict[str, str]:
    note = note.removeprefix(_MOUNT)
    return {"path": note} if "/" in note or note.endswith(".md") else {"file": note}


def _paths(paths: list[Path]) -> CommandResult:
    return _ok(f"{_MOUNT}{path.as_posix()}" for path in paths)


def _ok(lines: Iterable[str]) -> CommandResult:
    return CommandResult.ok("".join(f"{line}\n" for line in lines))
