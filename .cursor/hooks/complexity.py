#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAX_COGNITIVE = 15
SCOPES = ("app", "tests")
WRITE_TOOLS = {"Write", "StrReplace", "EditNotebook", "ApplyPatch"}

_STEER = (
    "§9 complexity: cut each flagged function. Each pass deletes a branch "
    "or a helper. Stop only when the next cut loses robustness, the "
    "caller-visible outcome, extensibility, or a significant tradeoff, and "
    "name that sacrifice. ARCHITECTURE.md §9 adoption gate, step 3."
)


def _state_file(conversation_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in conversation_id)
    directory = Path(tempfile.gettempdir()) / "obsidian-agent-complexity"
    directory.mkdir(exist_ok=True)
    return directory / (safe[:80] or "unknown")


def _in_scope(path: Path) -> bool:
    try:
        relative = path.resolve().relative_to(ROOT)
    except ValueError:
        return False
    return path.suffix == ".py" and relative.parts[0] in SCOPES


def _record(conversation_id: str, path: Path) -> None:
    if not _in_scope(path):
        return
    state = _state_file(conversation_id)
    existing = set(state.read_text().splitlines()) if state.exists() else set()
    existing.add(str(path.resolve()))
    state.write_text("\n".join(sorted(existing)) + "\n")


def _recorded(conversation_id: str) -> list[Path]:
    state = _state_file(conversation_id)
    if not state.exists():
        return []
    return [Path(line) for line in state.read_text().splitlines() if line]


def violations(paths: list[Path]) -> str:
    try:
        from complexipy import file_complexity
    except ImportError:
        return ""
    lines: list[str] = []
    for path in paths:
        if not path.is_file() or not _in_scope(path):
            continue
        try:
            result = file_complexity(str(path))
        except Exception:
            continue
        for fn in result.functions:
            if fn.complexity <= MAX_COGNITIVE:
                continue
            hint = ""
            plans = list(fn.refactor_plans or [])
            if plans and plans[0].title:
                hint = f" {plans[0].title}."
            lines.append(
                f"{path}:{fn.line_start} {fn.name} "
                f"cognitive {fn.complexity} > {MAX_COGNITIVE}.{hint}"
            )
    return "\n".join(lines)


def _steer(report: str) -> str:
    return f"{_STEER}\n{report}"


def _tool_path(payload: dict) -> Path | None:
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except json.JSONDecodeError:
            return None
    if not isinstance(tool_input, dict):
        return None
    for key in ("path", "file_path", "target_notebook"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return Path(value)
    return None


def handle(payload: dict) -> dict:
    event = payload.get("hook_event_name")
    conversation_id = str(payload.get("conversation_id") or "unknown")
    if event == "afterFileEdit":
        file_path = payload.get("file_path")
        if isinstance(file_path, str):
            _record(conversation_id, Path(file_path))
        return {}
    if event == "postToolUse":
        if payload.get("tool_name") not in WRITE_TOOLS:
            return {}
        path = _tool_path(payload)
        if path is None:
            return {}
        _record(conversation_id, path)
        report = violations([path])
        return {"additional_context": _steer(report)} if report else {}
    if event == "stop":
        if payload.get("status") != "completed":
            return {}
        if int(payload.get("loop_count") or 0) >= 3:
            return {}
        report = violations(_recorded(conversation_id))
        return {"followup_message": _steer(report)} if report else {}
    return {}


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        sys.stdout.write(json.dumps(handle(payload)))
    except Exception:
        sys.stdout.write("{}")


if __name__ == "__main__":
    main()
