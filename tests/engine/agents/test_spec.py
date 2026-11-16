"""Tests for AgentSpec prompt resolution and parsing."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.core.settings import AgentPromptConfig, AgentsConfig
from app.engine.agents.spec import AgentSpec


class _Out(BaseModel):
    title: str


def _make_spec(default: str = "Default prompt body") -> AgentSpec[_Out]:
    return AgentSpec(
        name="researcher",
        output_schema=_Out,
        default_system_prompt=default,
    )


def test_uses_default_prompt_when_yaml_override_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.engine.agents.spec.settings.agents", None)
    spec = _make_spec("hello")
    assert spec.system_prompt() == "hello"


def test_yaml_override_wins_over_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.engine.agents.spec.settings.agents",
        AgentsConfig(
            researcher=AgentPromptConfig(system_prompt="yaml override wins"),
            summarizer=AgentPromptConfig(),
            zettelkasten=AgentPromptConfig(),
            connect=AgentPromptConfig(),
        ),
    )
    spec = _make_spec("default body")
    assert spec.system_prompt() == "yaml override wins"


def test_rejects_unknown_agent_name() -> None:
    with pytest.raises(ValueError, match="unknown agent name"):
        AgentSpec(
            name="typo",  # type: ignore[arg-type]
            output_schema=_Out,
            default_system_prompt="x",
        )


def test_prompt_for_rejects_unknown_runtime_agent_name() -> None:
    cfg = AgentsConfig(
        researcher=AgentPromptConfig(),
        summarizer=AgentPromptConfig(),
        zettelkasten=AgentPromptConfig(),
        connect=AgentPromptConfig(),
    )

    with pytest.raises(ValueError, match="unknown agent name"):
        cfg.prompt_for("typo")  # type: ignore[arg-type]


def test_interpolates_output_format_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.engine.agents.spec.settings.agents", None)
    spec = _make_spec("Schema follows:\n$output_format")
    rendered = spec.system_prompt()
    assert "Schema follows:" in rendered
    assert "title: string," in rendered


def test_parse_round_trips_strict_json() -> None:
    spec = _make_spec()
    parsed = spec.parse('{"title": "ok"}')
    assert parsed == _Out(title="ok")


def test_agent_yaml_llm_keys_override_global_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _LLM:
        def model_dump(self, mode: str = "python") -> dict[str, object]:
            return {"model": "gpt-x", "temperature": 1.0}

    agent = AgentPromptConfig(llm={"temperature": 0.2})
    monkeypatch.setattr("app.engine.agents.spec.settings.llm", _LLM())
    monkeypatch.setattr(
        "app.engine.agents.spec.settings.agents",
        AgentsConfig(
            researcher=agent, summarizer=agent, zettelkasten=agent, connect=agent
        ),
    )
    kwargs = _make_spec().llm_kwargs()
    assert kwargs["model"] == "gpt-x"
    assert kwargs["temperature"] == 0.2
