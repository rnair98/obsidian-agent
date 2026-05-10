"""Tests for the layered structured-output parser."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.engine.parsing import StructuredParseError, parse_structured


class Sample(BaseModel):
    name: str
    score: int
    tags: list[str]


def test_strict_path_parses_clean_json() -> None:
    raw = '{"name": "alpha", "score": 10, "tags": ["a", "b"]}'
    out = parse_structured(raw, Sample)
    assert out == Sample(name="alpha", score=10, tags=["a", "b"])


def test_strips_json_code_fence() -> None:
    raw = '```json\n{"name": "alpha", "score": 10, "tags": []}\n```'
    out = parse_structured(raw, Sample)
    assert out.name == "alpha"


def test_strips_bare_code_fence() -> None:
    raw = '```\n{"name": "beta", "score": 1, "tags": []}\n```'
    out = parse_structured(raw, Sample)
    assert out.name == "beta"


def test_strips_uppercase_and_variant_fences() -> None:
    for tag in ("Json", "JSON", "jsonc", "json5"):
        raw = f'```{tag}\n{{"name": "x", "score": 0, "tags": []}}\n```'
        out = parse_structured(raw, Sample)
        assert out.name == "x"


def test_strips_yapping_prefix_and_suffix() -> None:
    raw = (
        "Sure! Here is the JSON you asked for:\n"
        '{"name": "gamma", "score": 7, "tags": ["x"]}\n'
        "Let me know if you need anything else."
    )
    out = parse_structured(raw, Sample)
    assert out.name == "gamma"
    assert out.tags == ["x"]


def test_recovers_trailing_comma_via_json_repair() -> None:
    raw = '{"name": "delta", "score": 3, "tags": ["a", "b",],}'
    out = parse_structured(raw, Sample)
    assert out.tags == ["a", "b"]


def test_recovers_unquoted_keys_via_json_repair() -> None:
    raw = '{name: "epsilon", score: 4, tags: ["a"]}'
    out = parse_structured(raw, Sample)
    assert out.name == "epsilon"


def test_picks_largest_balanced_block_when_multiple_present() -> None:
    raw = (
        'noise {"x": 1} more noise '
        '{"name": "zeta", "score": 9, "tags": ["q", "r"]} trailing'
    )
    out = parse_structured(raw, Sample)
    assert out.name == "zeta"


def test_raises_when_unrecoverable() -> None:
    with pytest.raises(StructuredParseError):
        parse_structured("totally not json at all", Sample)
