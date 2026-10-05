from pathlib import Path

from tests.support.sensors import (
    direct_write_violations,
    graph_workflow_violations,
    workflow_import_violations,
)

_REPO = Path(__file__).resolve().parents[2]
_FIXTURES = Path(__file__).resolve().parent / "sensors" / "fixtures"


def test_direct_write_sensor_flags_the_fixture() -> None:
    text = "\n".join(direct_write_violations(_FIXTURES / "direct_write.py"))
    assert "calls open()" in text
    assert "calls write_text()" in text
    assert "calls write_bytes()" in text
    assert "§10" in text


def test_direct_write_sensor_allows_filesystem_backend() -> None:
    assert direct_write_violations(_FIXTURES / "legal_write.py") == []


def test_nodes_and_tools_do_not_write_directly() -> None:
    hits: list[str] = []
    roots = (
        _REPO / "app" / "engine" / "nodes",
        _REPO / "app" / "engine" / "tools",
    )
    for root in roots:
        hits.extend(direct_write_violations(root))
    assert hits == []


def test_workflow_sensor_flags_an_unimported_module() -> None:
    hits = workflow_import_violations(_FIXTURES / "unregistered_workflow")
    assert any("side.py" in hit and "§9" in hit for hit in hits)


def test_workflow_modules_are_imported() -> None:
    assert workflow_import_violations(_REPO / "app" / "engine" / "workflows") == []


def test_graphs_do_not_register_workflows() -> None:
    assert graph_workflow_violations(_REPO / "app" / "engine" / "graphs") == []
