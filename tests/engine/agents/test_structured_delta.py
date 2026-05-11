from __future__ import annotations

from app.engine.agents.summarizer import SummarizerOutput
from app.engine.agents.zettelkasten import ZettelkastenNote, ZettelkastenOutput
from app.engine.nodes.builders.agent import structured_response_delta


def test_structured_response_delta_maps_summarizer_output_to_report_state() -> None:
    output = SummarizerOutput(
        report_content="# Report",
        executive_summary="Short",
        sources_used=["https://example.com"],
    )

    assert structured_response_delta(output) == {"report": "# Report"}


def test_structured_response_delta_maps_zettelkasten_output_to_notes_state() -> None:
    output = ZettelkastenOutput(
        notes=[
            ZettelkastenNote(
                id="note-a",
                title="Note A",
                content="Body",
                tags=["x"],
            )
        ]
    )

    assert structured_response_delta(output) == {
        "zettelkasten_notes": [
            {"id": "note-a", "title": "Note A", "content": "Body", "tags": ["x"]}
        ]
    }
