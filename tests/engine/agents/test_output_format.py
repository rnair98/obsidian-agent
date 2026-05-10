"""Tests for the TypeScript-flavored schema renderer."""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.engine.agents.output_format import render_output_format


class _Flat(BaseModel):
    name: str
    score: int = Field(..., description="Relevance score (1-10)")


class _Color(str, Enum):
    RED = "red"
    BLUE = "blue"


class _Nested(BaseModel):
    flat: _Flat
    tags: list[str]
    flag: Optional[bool]
    color: _Color
    mode: Literal["fast", "slow"]


def test_renders_primitives_with_description() -> None:
    out = render_output_format(_Flat)
    assert "name: string," in out
    assert "score: int,  // Relevance score (1-10)" in out
    assert out.startswith("Answer in JSON matching this schema:\n{")


def test_renders_nested_models_recursively() -> None:
    out = render_output_format(_Nested)
    assert "flat: {" in out
    assert "tags: string[]," in out


def test_renders_optional_as_union_with_null() -> None:
    out = render_output_format(_Nested)
    assert "flag: bool | null," in out


def test_renders_enum_members() -> None:
    out = render_output_format(_Nested)
    assert "color: 'red' | 'blue'," in out


def test_renders_literal_choices() -> None:
    out = render_output_format(_Nested)
    assert "mode: 'fast' | 'slow'," in out


def test_renders_variadic_tuple_as_array() -> None:
    class _Variadic(BaseModel):
        rows: tuple[int, ...]

    out = render_output_format(_Variadic)
    assert "rows: int[]," in out


def test_renders_fixed_length_tuple_preserving_member_types() -> None:
    class _Fixed(BaseModel):
        triple: tuple[str, int, float]

    out = render_output_format(_Fixed)
    assert "triple: [string, int, float]," in out


def test_renders_unparameterized_dict_without_raising() -> None:
    # ``typing.Dict`` (no params) has ``get_origin == dict`` but empty args,
    # so the renderer must fall back to a generic ``map<...>`` instead of
    # blowing up on a 2-tuple unpack.
    from typing import Dict  # noqa: UP035 — intentionally testing the legacy form

    class _Loose(BaseModel):
        payload: Dict  # noqa: UP006 — see above

    out = render_output_format(_Loose)
    assert "payload: map<string, unknown>," in out


def test_handles_recursive_reference() -> None:
    class _Tree(BaseModel):
        name: str
        children: list["_Tree"] = Field(default_factory=list)

    _Tree.model_rebuild()
    out = render_output_format(_Tree)
    assert "(recursive: _Tree)" in out
