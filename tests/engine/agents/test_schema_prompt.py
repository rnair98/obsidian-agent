"""Fitness: every named agent's schema is part of the prompt it actually runs."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from typing import Any, get_args

from pydantic import BaseModel

from app.engine.agents.spec import AgentSpec
from app.engine.agents.types import AgentName


def test_every_named_agent_publishes_its_schema_in_the_prompt() -> None:
    names = get_args(AgentName)
    assert names
    for name in names:
        module = importlib.import_module(f"app.engine.agents.{name}")
        spec = module.SPEC
        assert isinstance(spec, AgentSpec)
        assert spec.name == name

        rendered = spec.output_format()
        prompt = spec.system_prompt()
        assert "$output_format" not in prompt
        assert rendered in prompt

        for model in _model_tree(spec.output_schema):
            for field_name, field in model.model_fields.items():
                assert f"{field_name}:" in rendered
                if field.description:
                    assert field.description in rendered


def _model_tree(
    model: type[BaseModel],
    seen: set[type[BaseModel]] | None = None,
) -> Iterator[type[BaseModel]]:
    seen = set() if seen is None else seen
    if model in seen:
        return
    seen.add(model)
    yield model
    for field in model.model_fields.values():
        for nested in _nested_models(field.annotation):
            yield from _model_tree(nested, seen)


def _nested_models(annotation: Any) -> Iterator[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
        return
    for arg in get_args(annotation):
        yield from _nested_models(arg)
