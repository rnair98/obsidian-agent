"""``AgentSpec`` — co-located agent definition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from string import Template
from types import MappingProxyType
from typing import Any, Generic, TypeVar, cast, get_args

from pydantic import BaseModel

from app.core.settings import settings
from app.engine.agents.output_format import render_output_format
from app.engine.agents.types import AgentName, AgentTool
from app.engine.parsing import parse_structured

T = TypeVar("T", bound=BaseModel)

_EMPTY_OVERRIDES: Mapping[str, Any] = MappingProxyType({})
_AGENT_NAMES = frozenset(cast("tuple[AgentName, ...]", get_args(AgentName)))


@dataclass(frozen=True, slots=True)
class AgentSpec(Generic[T]):
    """Frozen bundle describing one agent.

    Not hashable in the general case — ``llm_overrides`` defaults to a
    ``MappingProxyType`` (no ``__hash__``) and callers may pass concrete
    ``list``/``dict`` values for ``tools``/``llm_overrides``. Treat
    instances as values, not dict keys.
    """

    name: AgentName
    output_schema: type[T]
    default_system_prompt: str
    tools: Sequence[AgentTool] = ()
    llm_overrides: Mapping[str, Any] = field(default_factory=lambda: _EMPTY_OVERRIDES)

    def __post_init__(self) -> None:
        if self.name not in _AGENT_NAMES:
            raise ValueError(f"unknown agent name: {self.name}")

    def output_format(self) -> str:
        return render_output_format(self.output_schema)

    def system_prompt(self) -> str:
        cfg = (
            settings.agents.prompt_for(self.name)
            if settings.agents is not None
            else None
        )
        raw = (
            cfg.system_prompt
            if cfg is not None and cfg.system_prompt
            else self.default_system_prompt
        )
        if "$output_format" in raw or "${output_format}" in raw:
            return Template(raw).safe_substitute(output_format=self.output_format())
        return raw

    def llm_kwargs(self) -> dict[str, Any]:
        base = settings.llm.model_dump(mode="python") if settings.llm else {}
        base.update(self.llm_overrides)
        return base

    def parse(self, raw: str) -> T:
        return parse_structured(raw, self.output_schema)
