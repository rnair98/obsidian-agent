"""Schema-aligned structured-output parsing with layered recovery.

The primary structured-output mechanism in this codebase is OpenAI's
Responses API + ``ProviderStrategy(...)`` which guarantees JSON matching
the target Pydantic schema. ``parse_structured`` exists for the seams
where we receive a raw string instead — e.g. tool arguments, persisted
artifacts, or non-OpenAI providers added later.

Recovery is layered, cheapest first:

1. Strict ``model_validate_json``.
2. Strip ``\u0060\u0060\u0060json ... \u0060\u0060\u0060`` code fences.
3. Extract the largest balanced ``{...}`` / ``[...]`` substring (handles
   prose prefix/suffix, a.k.a. "yapping").
4. ``json_repair.repair_json`` for trailing commas, unquoted keys,
   single quotes, missing brackets, comments, etc.

Each attempt is tagged on an OpenTelemetry span so Phoenix can show
which stage succeeded — recovering the pre-parse / post-parse trace
fidelity that BAML's ``Collector`` provides natively.
"""

from __future__ import annotations

import re
from typing import TypeVar

from json_repair import repair_json
from opentelemetry import trace
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_tracer = trace.get_tracer(__name__)
_FENCE_RE = re.compile(r"^```\w*\s*\n?(.*?)\n?```\s*$", re.DOTALL | re.IGNORECASE)


class StructuredParseError(ValueError):
    """Raised when no recovery stage produces a valid model."""


def parse_structured(raw: str, model: type[T]) -> T:
    """Parse ``raw`` into ``model``, attempting recovery on failure.

    Args:
        raw: The free-form string emitted by the LLM (or stored in a
            tool call argument, etc.).
        model: The Pydantic model to validate against.

    Returns:
        A validated instance of ``model``.

    Raises:
        StructuredParseError: When every recovery stage fails. The
            underlying ``ValidationError`` is chained for inspection.
    """
    last_err: Exception | None = None

    with _tracer.start_as_current_span("structured_output.parse") as span:
        span.set_attribute("schema", model.__name__)
        span.set_attribute("raw.len", len(raw))

        for stage, candidate in _candidates(raw):
            try:
                obj = model.model_validate_json(candidate)
            except ValidationError as err:
                last_err = err
                continue
            span.set_attribute("parse.stage", stage)
            return obj

        span.set_attribute("parse.failed", True)
        if last_err is not None:
            span.record_exception(last_err)

    raise StructuredParseError(
        f"Could not parse {model.__name__} from raw output"
    ) from last_err


def _candidates(raw: str):
    """Yield ``(stage_name, candidate_text)`` in increasing recovery cost."""
    yield "strict", raw

    fenced = _FENCE_RE.match(raw.strip())
    if fenced is not None:
        yield "fenced", fenced.group(1)

    block = _largest_balanced(raw)
    if block is not None and block != raw.strip():
        yield "yapping_strip", block

    # Try ``json_repair`` against both the extracted balanced block and the
    # full raw input. The block is preferred (cheapest, most likely to
    # validate) but a malformed extractor result must not foreclose
    # recovery from the surrounding prose.
    seen: set[str] = set()
    for stage, candidate in (("json_repair_block", block), ("json_repair_raw", raw)):
        if candidate is None:
            continue
        repaired = repair_json(candidate, return_objects=False)
        if (
            isinstance(repaired, str)
            and repaired
            and repaired != candidate
            and repaired not in seen
        ):
            seen.add(repaired)
            yield stage, repaired


def _largest_balanced(s: str) -> str | None:
    """Return the longest bracket-balanced ``{...}`` or ``[...]`` substring.

    Walks the input in a single pass per opener/closer pair and tracks the
    longest fully-closed run. Strings inside the JSON are not parsed —
    bracket characters embedded in strings can produce false positives, but
    those cases fall through to ``json_repair`` which handles them.
    """
    best: str | None = None
    for opener, closer in (("{", "}"), ("[", "]")):
        depth = 0
        start = -1
        for i, ch in enumerate(s):
            if ch == opener:
                if depth == 0:
                    start = i
                depth += 1
            elif ch == closer and depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    candidate = s[start : i + 1]
                    if best is None or len(candidate) > len(best):
                        best = candidate
                    start = -1
    return best
