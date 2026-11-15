"""Blobless bare mirrors and the Seatbelt-confined git runner (ARCHITECTURE.md §10)."""

from __future__ import annotations

import base64
import functools
import os
import shutil
import subprocess
import sys
from pathlib import Path

READ_SUBCOMMANDS = frozenset(
    {
        "blame",
        "cat-file",
        "describe",
        "diff",
        "for-each-ref",
        "grep",
        "log",
        "ls-tree",
        "merge-base",
        "name-rev",
        "rev-list",
        "rev-parse",
        "shortlog",
        "show",
    }
)

_PROFILE = """
(version 1)
(deny default)
(allow process-fork sysctl-read mach-lookup file-read-metadata signal)
(allow ipc-posix-shm system-socket)
(allow process-exec (literal (param "GIT")) (literal (param "REMOTE_HTTP")))
(allow file-read*
  (literal "/") (subpath "/usr/lib") (subpath "/System") (subpath "/dev")
  (subpath (param "TOOLCHAIN")) (subpath (param "MIRROR"))
  (subpath "/private/var/db/dyld") (literal "/private/var/db/xcode_select_link")
  (subpath "/private/etc/ssl") (subpath "/Library/Keychains")
  (subpath "/private/var/db/mds"))
(allow file-write* (subpath (param "OBJECTS")) (literal "/dev/null"))
(allow network-outbound (remote tcp "*:443") (literal "/private/var/run/mDNSResponder"))
"""


class MirrorError(RuntimeError):
    pass


@functools.cache
def git_binary() -> Path:
    """The real git binary, not the /usr/bin xcrun shim, so Seatbelt can pin exec."""
    if sys.platform != "darwin" or shutil.which("sandbox-exec") is None:
        raise MirrorError(
            "git history commands need macOS Seatbelt (sandbox-exec); "
            "unavailable on this host"
        )
    found = subprocess.run(
        ["xcrun", "-f", "git"],
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
    )
    return Path(found.stdout.strip()).resolve()


def ensure_mirror(
    mirror: Path, url: str, token: str | None, *, timeout: float
) -> subprocess.CompletedProcess[bytes]:
    """Clone a blobless bare mirror, or refresh its branches, tags and HEAD."""
    env = _env(token, scheme=url.partition("://")[0])
    if not mirror.exists():
        return _clone(mirror, url, env, timeout)
    if (mirror / "objects" / "info" / "alternates").exists():
        raise MirrorError(f"{mirror} borrows objects from another store")
    refspecs = ["+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*"]
    fetched = _host(
        mirror, ["fetch", "--quiet", "--prune", "origin", *refspecs], env, timeout
    )
    if fetched.returncode != 0:
        return fetched
    remote = _host(mirror, ["ls-remote", "--symref", "origin", "HEAD"], env, timeout)
    head = remote.stdout.split(b"\t", 1)[0].removeprefix(b"ref: ").decode()
    if remote.returncode != 0 or not head.startswith("refs/heads/"):
        return remote
    return _host(mirror, ["symbolic-ref", "HEAD", head], env, timeout)


def _clone(
    mirror: Path, url: str, env: dict[str, str], timeout: float
) -> subprocess.CompletedProcess[bytes]:
    """Clone beside the target and rename, so a killed clone leaves no mirror."""
    mirror.parent.mkdir(parents=True, exist_ok=True)
    partial = mirror.with_name(f".{mirror.name}.{os.getpid()}.partial")
    shutil.rmtree(partial, ignore_errors=True)
    argv = [str(git_binary()), "clone", "--quiet", "--bare", "--filter=blob:none"]
    try:
        proc = subprocess.run(
            [*argv, url, str(partial)],
            capture_output=True,
            timeout=timeout,
            env=env,
            cwd=mirror.parent,
            stdin=subprocess.DEVNULL,
        )
        if proc.returncode == 0:
            partial.rename(mirror)
        return proc
    finally:
        shutil.rmtree(partial, ignore_errors=True)


def _host(
    mirror: Path, args: list[str], env: dict[str, str], timeout: float
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [str(git_binary()), "--git-dir", str(mirror), *args],
        capture_output=True,
        timeout=timeout,
        env=env,
        cwd=mirror,
        stdin=subprocess.DEVNULL,
    )


def run_git(
    mirror: Path, args: list[str], token: str | None, *, timeout: float
) -> subprocess.CompletedProcess[bytes]:
    """Run one agent git command against `mirror` inside the Seatbelt profile."""
    git = git_binary()
    toolchain = git.parents[2]
    mirror = mirror.resolve()
    argv = [
        "sandbox-exec",
        "-D", f"TOOLCHAIN={toolchain}",
        "-D", f"GIT={git}",
        "-D", f"REMOTE_HTTP={toolchain / 'usr/libexec/git-core/git-remote-http'}",
        "-D", f"MIRROR={mirror}",
        "-D", f"OBJECTS={mirror / 'objects'}",
        "-p", _PROFILE,
        str(git), "--git-dir", str(mirror), *args,
    ]  # fmt: skip
    return subprocess.run(
        argv,
        capture_output=True,
        timeout=timeout,
        env=_env(token),
        cwd=mirror,
        stdin=subprocess.DEVNULL,
    )


_TRANSPORT_CONFIG = (
    ("protocol.allow", "never"),
    ("http.followRedirects", "false"),
    ("http.sslVerify", "true"),
    ("http.proxy", ""),
    ("credential.helper", ""),
    ("core.hooksPath", os.devnull),
)


def _env(token: str | None, scheme: str = "https") -> dict[str, str]:
    config = [*_TRANSPORT_CONFIG, (f"protocol.{scheme}.allow", "always")]
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        header = f"Authorization: Basic {basic}"
        config.append(("http.https://github.com/.extraHeader", header))
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/nonexistent",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": scheme,
        "GIT_PAGER": "cat",
        "GIT_CONFIG_COUNT": str(len(config)),
    }
    for index, (key, value) in enumerate(config):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    return env
