"""Import-chain smoke tests.

These would have caught the NodeName/Workflow rename drift, the
FilesystemBackend Protocol validation error, and the stale
app.logger import path in a single pytest run.
"""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def test_every_app_module_imports_first_in_a_fresh_interpreter() -> None:
    """An import cycle hides when another module happens to load first."""
    modules = sorted(
        ".".join(path.relative_to(_REPO).with_suffix("").parts).removesuffix(".__init__")
        for path in (_REPO / "app").rglob("*.py")
    )

    def run(module: str) -> tuple[str, str]:
        result = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            cwd=_REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        error = result.stderr.strip().splitlines()[-1] if result.returncode else ""
        return module, error

    with ThreadPoolExecutor(max_workers=8) as pool:
        failures = {module: err for module, err in pool.map(run, modules) if err}
    assert not failures, f"modules that fail when imported first: {failures}"


def test_app_main_imports() -> None:
    from app.main import app

    assert app is not None


def test_workflow_registry_populates_on_workflow_import() -> None:
    import app.engine.workflows  # noqa: F401
    from app.engine.nodes.types import WorkflowName
    from app.engine.registry import list_workflows

    registered = set(list_workflows())
    named = {name.value for name in WorkflowName}
    assert registered == named, (
        "§9 workflow: WorkflowName and the @workflow registry disagree "
        f"(registered={sorted(registered)}, named={sorted(named)}). "
        "ARCHITECTURE.md §9 and §10."
    )


def test_tools_are_importable() -> None:
    """Importing tools triggers @tool(parse_docstring=True) validation.

    A Google-style docstring regression would raise ValueError at import.
    """
    from app.engine import artifacts  # noqa: F401
    from app.engine.tools import MCP_TOOLS, OPENAI_TOOLS, shell  # noqa: F401

    assert OPENAI_TOOLS
    assert MCP_TOOLS


def test_tool_schemas_describe_every_parameter() -> None:
    """Every @tool's JSON schema must cover each of its parameters."""
    from app.engine.tools.shell import shell

    tools = [
        shell,
    ]
    for t in tools:
        schema = t.args_schema.model_json_schema()
        for prop_name, prop in schema.get("properties", {}).items():
            assert prop.get("description"), (
                f"{t.name} parameter {prop_name!r} missing description — "
                "Google-style docstring drift"
            )
