from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

import httpx

from app.core.settings import settings
from app.engine.backends.protocol import FilesystemBackend
from app.engine.obsidian import ObsidianVaultOperations
from app.engine.similarity import SimilarityIndex, http_embedder
from app.engine.vaults import VaultLayout
from app.harness.commands import CommandSpec, first_flag, unsupported_flag
from app.harness.results import CommandResult
from app.harness.session import WorkspaceSession

_MOUNT = "/vault/"


class VaultCommand:
    """Read the vault's note graph: search, similar, links, backlinks, tags."""

    spec = CommandSpec(
        name="vault",
        forms=(
            "vault search QUERY",
            "vault similar TEXT",
            "vault links NOTE",
            "vault backlinks NOTE",
            "vault tags",
        ),
    )

    def __init__(self, layout: VaultLayout, assets: FilesystemBackend) -> None:
        self._vault = ObsidianVaultOperations(layout)
        self._assets = assets

    def __call__(self, _session: WorkspaceSession, args: list[str]) -> CommandResult:
        if flag := first_flag(args):
            return unsupported_flag(self.spec, flag)
        match args:
            case ["similar", text]:
                return self._similar(text)
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

    def _similar(self, text: str) -> CommandResult:
        url = settings.EMBEDDING_URL
        index = SimilarityIndex(self._vault, self._assets, http_embedder(url))
        try:
            neighbors = index.similar(text)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            return CommandResult.error(
                f"vault similar: embedding server at {url} failed ({exc!r}); "
                "start it with `just embed`\n"
            )
        except sqlite3.Error as exc:
            return CommandResult.error(
                f"vault similar: index {index.db_file} failed ({exc}); it is "
                "rebuildable, so delete it after an embedding model change\n"
            )
        return _ok(
            f"{_MOUNT}{path.as_posix()} {score:.3f}" for path, score in neighbors
        )


def _note(note: str) -> dict[str, str]:
    note = note.removeprefix(_MOUNT)
    return {"path": note} if "/" in note or note.endswith(".md") else {"file": note}


def _paths(paths: list[Path]) -> CommandResult:
    return _ok(f"{_MOUNT}{path.as_posix()}" for path in paths)


def _ok(lines: Iterable[str]) -> CommandResult:
    return CommandResult.ok("".join(f"{line}\n" for line in lines))
