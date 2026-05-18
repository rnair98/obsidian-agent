from __future__ import annotations

import hashlib
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

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
    if spec is None:
        return _default_vault()
    if isinstance(spec, LocalVaultRequest):
        return _local_vault(spec.path)
    if isinstance(spec, GitVaultRequest):
        return _git_vault(spec)
    raise TypeError(f"unsupported vault request: {type(spec)!r}")


def ensure_vault_layout(layout: VaultLayout) -> VaultLayout:
    for directory in (
        layout.root / ".obsidian",
        layout.notes_dir,
        layout.outputs_dir,
        layout.memories_dir,
    ):
        layout.backend.mkdir(directory)
    return layout


def _default_vault() -> VaultLayout:
    base_path = settings.filesystem.base_path / settings.VAULT_DIR
    return ensure_vault_layout(
        VaultLayout(
            backend=get_filesystem_backend(
                backend_type=settings.filesystem.backend_type,
                base_path=base_path,
            ),
            root=Path("."),
            notes_dir=Path("notes"),
            outputs_dir=Path("outputs"),
            memories_dir=Path(".memories"),
        )
    )


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


def _git_vault(spec: GitVaultRequest) -> VaultLayout:
    _validate_git_operand("url", spec.url)
    if spec.ref is not None:
        _validate_git_operand("ref", spec.ref)
    cache_key = _cache_key(spec)
    cache_path = settings.filesystem.base_path / MANAGED_GIT_VAULTS_DIR / cache_key
    # Serialize clone/fetch on the same cache path so concurrent requests
    # don't race past an existence check into two competing `git clone`s.
    with _git_vault_lock(cache_key):
        if not cache_path.exists():
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            _run_git(["clone", "--", spec.url, str(cache_path)])
        else:
            if spec.ref is None:
                _run_git(["-C", str(cache_path), "pull", "--ff-only"])
            else:
                _run_git(["-C", str(cache_path), "fetch", "--all", "--prune"])
        if spec.ref:
            _run_git(["-C", str(cache_path), "checkout", "--", spec.ref])
    return _local_vault(cache_path)


def _cache_key(spec: GitVaultRequest) -> str:
    raw = f"{spec.url}\0{spec.ref or ''}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _validate_git_operand(name: str, value: str) -> None:
    if value.startswith("-"):
        raise VaultResolutionError(f"git vault {name} must not start with '-'")


def _run_git(args: list[str]) -> None:
    try:
        completed = subprocess.run(
            ["git", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=GIT_OPERATION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise VaultResolutionError(
            f"git vault operation timed out after {GIT_OPERATION_TIMEOUT_SECONDS:.0f}s"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise VaultResolutionError(f"git vault operation failed: {detail}")
