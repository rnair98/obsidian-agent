from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from app.core.logger import logger
from app.core.settings import settings
from app.engine.backends import get_filesystem_backend
from app.engine.backends.protocol import FilesystemBackend
from app.engine.schema import GitVaultRequest, LocalVaultRequest, ResearchRequest

MANAGED_GIT_VAULTS_DIR = Path(".vaults")
GIT_OPERATION_TIMEOUT_SECONDS = 120.0

# Per-cache-path lock to serialize concurrent git clones/fetches targeting the
# same vault directory. Locks are tracked in this process only; cross-process
# concurrency on the same vault is a separate concern (and rare in practice).
_GIT_VAULT_LOCKS_GUARD = threading.Lock()
_GIT_VAULT_LOCKS: dict[str, threading.Lock] = {}


def _git_vault_lock(cache_key: str) -> threading.Lock:
    with _GIT_VAULT_LOCKS_GUARD:
        lock = _GIT_VAULT_LOCKS.get(cache_key)
        if lock is None:
            lock = threading.Lock()
            _GIT_VAULT_LOCKS[cache_key] = lock
        return lock


class VaultResolutionError(ValueError):
    """Raised when a request-provided vault cannot be prepared."""


@dataclass(frozen=True, slots=True)
class VaultLayout:
    backend: FilesystemBackend
    root: Path
    notes_dir: Path
    outputs_dir: Path
    memories_dir: Path


def resolve_vault(request: ResearchRequest) -> VaultLayout:
    spec = request.vault
    if isinstance(spec, LocalVaultRequest):
        return _local_vault(_approved_local_path(spec.path))

    return _git_vault(spec)


def ensure_vault_layout(layout: VaultLayout) -> VaultLayout:
    for directory in (
        layout.root / ".obsidian",
        layout.notes_dir,
        layout.outputs_dir,
        layout.memories_dir,
    ):
        layout.backend.mkdir(directory)
    return layout


def _local_vault(path: Path) -> VaultLayout:
    return ensure_vault_layout(
        VaultLayout(
            backend=get_filesystem_backend(base_path=path),
            root=Path("."),
            notes_dir=Path("notes"),
            outputs_dir=Path("outputs"),
            memories_dir=Path(".memories"),
        )
    )


def _approved_local_path(path: Path) -> Path:
    # Exact server-selected vaults, not caller-selected descendants or aliases.
    if not path.is_absolute() or path != path.resolve():
        raise VaultResolutionError("Local vault must be an absolute canonical path")
    approved = settings.security.local_vaults
    if not any(p.is_absolute() and p == p.resolve() and p == path for p in approved):
        raise VaultResolutionError("Local vault is not approved")
    return path


def _git_vault(spec: GitVaultRequest) -> VaultLayout:
    _validate_git_operand("url", spec.url)
    _validate_git_operand("ref", spec.ref)
    if (
        not re.fullmatch(
            r"https://github\.com/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+\.git", spec.url
        )
        or spec.url not in settings.security.git_repositories
    ):
        raise VaultResolutionError("Git repository is not approved")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/@-]{0,255}", spec.ref):
        raise VaultResolutionError("Invalid git ref")
    if ".." in spec.ref or "//" in spec.ref or "@{" in spec.ref:
        raise VaultResolutionError("Invalid git ref")
    cache_key = _cache_key(spec)
    base = settings.filesystem.base_path.resolve()
    cache_path = base / MANAGED_GIT_VAULTS_DIR / cache_key
    if cache_path.resolve() != cache_path:
        raise VaultResolutionError("Git vault cache must not contain symlinks")
    # Serialize clone/fetch on the same cache path so concurrent requests
    # don't race past an existence check into two competing `git clone`s.
    with _git_vault_lock(cache_key):
        if not cache_path.exists():
            cache_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            _run_git(
                [
                    "clone",
                    "--no-checkout",
                    "--template=",
                    "--",
                    spec.url,
                    str(cache_path),
                ]
            )
        _validate_cached_git_config(cache_path, spec.url)
        _run_git(["-C", str(cache_path), "fetch", "--", spec.url, spec.ref])
        _run_git(["-C", str(cache_path), "checkout", "--detach", "FETCH_HEAD", "--"])
    return _local_vault(cache_path)


def _cache_key(spec: GitVaultRequest) -> str:
    raw = f"{spec.url}\0{spec.ref}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _validate_git_operand(name: str, value: str) -> None:
    if not value.strip():
        raise VaultResolutionError(f"git vault {name} must not be empty")
    if value.startswith("-"):
        raise VaultResolutionError(f"git vault {name} must not start with '-'")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise VaultResolutionError(f"git vault {name} contains control characters")


def _validate_cached_git_config(path: Path, url: str) -> None:
    """Reject cached config that could rewrite URLs, enable hooks or credentials."""
    config_path = path / ".git" / "config"
    if config_path.resolve() != config_path or not config_path.is_file():
        raise VaultResolutionError("Invalid git vault cache")
    # Let Git parse its own grammar, without following include directives or
    # opening an ambient repository. Config inspection performs no transport.
    raw = _run_git(
        ["config", "--file", str(config_path), "--no-includes", "--null", "--list"]
    )
    core_keys = {
        "core.repositoryformatversion",
        "core.filemode",
        "core.bare",
        "core.logallrefupdates",
        "core.ignorecase",
        "core.precomposeunicode",
    }
    for entry in raw.split("\0"):
        if not entry:
            continue
        key, separator, value = entry.partition("\n")
        allowed = separator and (
            key in core_keys
            or key == "remote.origin.fetch"
            or (key == "remote.origin.url" and value == url)
            or (
                key.startswith("branch.")
                and key.endswith(".remote")
                and value == "origin"
            )
            or (key.startswith("branch.") and key.endswith(".merge"))
        )
        if not allowed:
            raise VaultResolutionError("Unsafe git vault cache configuration")


def _run_git(args: list[str]) -> str:
    try:
        with tempfile.TemporaryDirectory(prefix="vault-git-") as isolated_home:
            completed = subprocess.run(
                [
                    "git",
                    "-c",
                    "protocol.allow=never",
                    "-c",
                    "protocol.https.allow=always",
                    "-c",
                    "http.followRedirects=false",
                    "-c",
                    "http.sslVerify=true",
                    "-c",
                    "http.proxy=",
                    "-c",
                    "credential.helper=",
                    "-c",
                    "core.hooksPath=/dev/null",
                    *args,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=GIT_OPERATION_TIMEOUT_SECONDS,
                cwd=isolated_home,
                env={
                    "PATH": os.defpath,
                    "HOME": isolated_home,
                    "LANG": "C.UTF-8",
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": os.devnull,
                    "GIT_TERMINAL_PROMPT": "0",
                    "GIT_ALLOW_PROTOCOL": "https",
                },
            )
    except subprocess.TimeoutExpired as exc:
        raise VaultResolutionError(
            f"git vault operation timed out after {GIT_OPERATION_TIMEOUT_SECONDS:.0f}s"
        ) from exc
    except OSError as exc:
        raise VaultResolutionError("git vault worker unavailable") from exc
    if completed.returncode != 0:
        # Server-side only: the API maps this error to a generic 400.
        logger.warning(
            "git {} exited {}: {}",
            args[0] if args[0] != "-C" else args[2],
            completed.returncode,
            (completed.stderr or "").strip()[-2000:],
        )
        raise VaultResolutionError("git vault operation failed")
    return completed.stdout or ""
