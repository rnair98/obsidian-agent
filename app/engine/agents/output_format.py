"""Render Pydantic schemas as token-efficient TypeScript-flavored signatures."""

from __future__ import annotations

from enum import Enum
from types import NoneType, UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel

_PRIMITIVES: dict[type, str] = {
    str: "string",
    int: "int",
    float: "float",
    bool: "bool",
    NoneType: "null",
}


def render_output_format(model: type[BaseModel], *, indent: int = 2) -> str:
    """Render ``model`` as a TypeScript-flavored schema descriptor."""
    seen: frozenset[type] = frozenset()
    body = _render_object(model, indent_size=indent, prefix=" " * indent, seen=seen)
    return f"Answer in JSON matching this schema:\n{{\n{body}\n}}"


def _render_object(
    model: type[BaseModel],
    *,
    indent_size: int,
    prefix: str,
    seen: frozenset[type],
) -> str:
    if model in seen:
        return f"{prefix}// (recursive: {model.__name__})"
    seen = seen | {model}

    lines: list[str] = []
    for name, field in model.model_fields.items():
        type_str = _render_type(field.annotation, indent_size, prefix, seen)
        comment = f"  // {field.description}" if field.description else ""
        lines.append(f"{prefix}{name}: {type_str},{comment}")
    return "\n".join(lines)


def _render_type(
    tp: Any,
    indent_size: int,
    prefix: str,
    seen: frozenset[type],
) -> str:
    origin = get_origin(tp)
    args = get_args(tp)

    if origin in (Union, UnionType):
        non_none = [a for a in args if a is not NoneType]
        if len(non_none) == 1 and NoneType in args:
            return f"{_render_type(non_none[0], indent_size, prefix, seen)} | null"
        return " | ".join(_render_type(a, indent_size, prefix, seen) for a in args)

    if origin is tuple:
        if not args:
            return "unknown[]"
        if len(args) == 2 and args[1] is Ellipsis:
            return f"{_render_type(args[0], indent_size, prefix, seen)}[]"
        rendered = ", ".join(_render_type(a, indent_size, prefix, seen) for a in args)
        return f"[{rendered}]"

    if origin in (list, set, frozenset):
        inner = args[0] if args else object
        return f"{_render_type(inner, indent_size, prefix, seen)}[]"

    if origin is dict:
        if len(args) != 2:
            return "map<string, unknown>"
        key_type, value_type = args
        return (
            f"map<{_render_type(key_type, indent_size, prefix, seen)}, "
            f"{_render_type(value_type, indent_size, prefix, seen)}>"
        )

    if origin is Literal:
        return " | ".join(repr(a) for a in args)

    if isinstance(tp, type) and issubclass(tp, BaseModel):
        deeper = prefix + " " * indent_size
        body = _render_object(tp, indent_size=indent_size, prefix=deeper, seen=seen)
        return f"{{\n{body}\n{prefix}}}"

    if isinstance(tp, type) and issubclass(tp, Enum):
        return " | ".join(repr(member.value) for member in tp)

    if isinstance(tp, type) and tp in _PRIMITIVES:
        return _PRIMITIVES[tp]

    return getattr(tp, "__name__", str(tp))
