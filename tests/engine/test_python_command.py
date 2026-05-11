from __future__ import annotations

from app.engine.workspace_commands.python import PythonCommand
from app.harness.session import WorkspaceSession


def test_python_command_runs_inline_code_with_monty() -> None:
    session = WorkspaceSession.scratch()
    command = PythonCommand()

    result = command(session, ["-c", "print(6 * 7)"])

    assert result.exit_code == 0
    assert result.stdout == "42\n"


def test_python_command_runs_workspace_script_with_monty() -> None:
    session = WorkspaceSession.scratch()
    session.run('write analysis.py -- "values = [1, 2, 3]\nprint(sum(values))"')
    command = PythonCommand()

    result = command(session, ["analysis.py"])

    assert result.exit_code == 0
    assert result.stdout == "6\n"


def test_python_command_reports_monty_errors_on_stderr() -> None:
    session = WorkspaceSession.scratch()
    command = PythonCommand()

    result = command(session, ["-c", "unknown_name + 1"])

    assert result.exit_code == 1
    assert "unknown_name" in result.stderr


def test_python_command_rejects_oversmart_module_flag_with_supported_forms() -> None:
    session = WorkspaceSession.scratch()
    command = PythonCommand()

    result = command(session, ["-m", "json.tool"])

    assert result.exit_code == 2
    assert result.stderr == (
        "python: unsupported flag: -m; supported forms: "
        "python -c code; python path.py\n"
    )
