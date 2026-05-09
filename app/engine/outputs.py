"""Backwards-compatible re-exports.

Schema definitions live next to their prompts under
``app/engine/agents/<name>.py``. This module re-exports them so older
imports continue to work; new code should import from
``app.engine.agents.<name>`` directly.
"""

from app.engine.agents.researcher import ResearcherOutput, Source
from app.engine.agents.summarizer import SummarizerOutput
from app.engine.agents.zettelkasten import ZettelkastenNote, ZettelkastenOutput

__all__ = [
    "Source",
    "ResearcherOutput",
    "SummarizerOutput",
    "ZettelkastenNote",
    "ZettelkastenOutput",
]
