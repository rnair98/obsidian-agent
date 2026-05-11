from __future__ import annotations

import pydantic_monty

from app.harness.commands import CommandSpec
from app.harness.results import CommandResult
from app.harness.session import WorkspaceSession


class PythonCommand:
    """Run agent-written Python snippets through Monty, not a host process."""

    spec = CommandSpec(name="python", forms=("python -c code", "python path.py"))

    def __call__(self, session: WorkspaceSession, args: list[str]) -> CommandResult:
        if not args:
            return CommandResult.error(
                "python: expected -c code or script path\n",
                exit_code=2,
            )
        try:
            code, script_name = self._code_from_args(session, args)
            collector = pydantic_monty.CollectStreams()
            pydantic_monty.Monty(code, script_name=script_name).run(
                print_callback=collector,
            )
        except _UnsupportedPythonFlag as exc:
            return CommandResult.error(f"python: {exc}\n", exit_code=2)
        except Exception as exc:
            return CommandResult.error(f"python: {exc}\n")
        return CommandResult.ok(_render_streams(collector.output))

    def _code_from_args(
        self,
        session: WorkspaceSession,
        args: list[str],
    ) -> tuple[str, str]:
        if args[0] == "-c":
            if len(args) != 2:
                raise ValueError("python -c expects exactly one code argument")
            return args[1], "<workspace -c>"
        if args[0].startswith("-"):
            raise _UnsupportedPythonFlag(args[0])
        if len(args) != 1:
            raise ValueError("python expects one script path")
        script_path = session._resolve(args[0])
        event = session._audit("read", script_path)
        if not event.allowed:
            raise PermissionError("permission denied")
        return session.backend.read_text(script_path), script_path


def _render_streams(streams: list[tuple[str, str]]) -> str:
    return "".join(text for _, text in streams)


class _UnsupportedPythonFlag(ValueError):
    def __init__(self, flag: str) -> None:
        super().__init__(
            f"unsupported flag: {flag}; supported forms: python -c code; python path.py"
        )
