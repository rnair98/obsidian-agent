from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.constants import END, START
from langgraph.graph import StateGraph

from app.engine.workflows.compose import compose_graphs


class _State(TypedDict, total=False):
    n: int
    trail: list[str]


def _graph(node: str, step):
    graph = StateGraph(_State)
    graph.add_node(node, step)
    graph.add_edge(START, node)
    graph.add_edge(node, END)
    return graph


def _add(amount: int, label: str):
    def step(state: _State) -> _State:
        return {
            "n": state.get("n", 0) + amount,
            "trail": [*state.get("trail", []), label],
        }

    return step


def test_compose_graphs_rejects_an_empty_workflow() -> None:
    with pytest.raises(ValueError, match="at least one graph"):
        compose_graphs((), MemorySaver())


@pytest.mark.asyncio
async def test_one_graph_keeps_its_own_nodes() -> None:
    compiled = compose_graphs(
        (("only", _graph("a", _add(1, "a"))),),
        MemorySaver(),
    )
    names = set(compiled.get_graph().nodes)
    assert "a" in names
    assert "only" not in names
    out = await compiled.ainvoke(
        {"n": 0, "trail": []},
        config={"configurable": {"thread_id": "one"}},
    )
    assert out == {"n": 1, "trail": ["a"]}


@pytest.mark.asyncio
async def test_several_graphs_share_one_state() -> None:
    compiled = compose_graphs(
        (
            ("ga", _graph("a", _add(1, "a"))),
            ("gb", _graph("b", _add(10, "b"))),
        ),
        MemorySaver(),
    )
    names = set(compiled.get_graph().nodes)
    assert {"ga", "gb"} <= names
    out = await compiled.ainvoke(
        {"n": 0, "trail": []},
        config={"configurable": {"thread_id": "many"}},
    )
    assert out["n"] == 11
    assert out["trail"] == ["a", "b"]
