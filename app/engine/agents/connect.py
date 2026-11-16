from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.engine.agents.spec import AgentSpec

Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)
]
Quote = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)
]


class Bridge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    a: str
    b: str
    mechanism: Text
    mapping: Text
    limitation: Text
    evidence_a: Quote
    evidence_b: Quote


class ConnectOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bridges: list[Bridge] = Field(max_length=8)


SPEC = AgentSpec(name="connect", output_schema=ConnectOutput)
