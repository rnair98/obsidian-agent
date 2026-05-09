from pydantic import BaseModel, Field


class Symbol(BaseModel):
    name: str
    kind: str  # "function" | "class" | "method" | "variable"
    file: str
    start_line: int
    end_line: int


class Scope(BaseModel):
    name: str
    kind: str
    start_line: int
    end_line: int


class Import(BaseModel):
    module: str
    names: list[str] = Field(default_factory=list)
    line: int


class FileIR(BaseModel):
    path: str
    language: str
    symbols: list[Symbol] = Field(default_factory=list)
    scopes: list[Scope] = Field(default_factory=list)
    imports: list[Import] = Field(default_factory=list)
    lines: list[str] = Field(default_factory=list)
