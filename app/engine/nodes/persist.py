from pathlib import Path

from app.engine.schema import ResearchState
from app.engine.tools.io import persist_memories, write_sources
from app.settings import settings


def persist_artifacts(state: ResearchState) -> ResearchState:
    sources_dir = settings.OUTPUT_DIR
    write_sources(sources_dir / "sources.csv", state.sources)
    persist_memories(
        settings.MEMORIES_DIR,
        state.topic,
        state.research_notes,
        state.key_insights,
        state.reasoning,
        state.sources,
        Path("outputs") / "report.md",
    )
    return state
