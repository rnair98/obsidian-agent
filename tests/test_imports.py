"""Import-chain smoke tests.

These would have caught the NodeName/Workflow rename drift, the
FilesystemBackend Protocol validation error, and the stale
app.logger import path in a single pytest run.
"""

from __future__ import annotations


def test_app_main_imports() -> None:
    from app.main import app

    assert app is not None


def test_workflow_registry_populates_on_graph_import() -> None:
    import app.engine.graphs  # noqa: F401
    from app.engine.registry import list_workflows

    assert set(list_workflows()) == {
        "research",
        "researcher",
        "summarizer",
        "zettelkasten",
    }


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
