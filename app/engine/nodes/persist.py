from app.core.paths import DEFAULT_REPORT_PATH
from app.core.settings import settings
from app.engine.backends import artifacts_backend
from app.engine.persistence import persist_memories, write_sources
from app.engine.schema import ResearchState


def persist_artifacts(state: ResearchState) -> dict:
    """Side-effect node: write sources.csv and memory markdown.

    Returns an empty delta — LangGraph merges this with the existing state,
    so there's no need to echo every field back through the checkpointer.
    """
    backend = artifacts_backend()
    sources_dir = settings.OUTPUT_DIR
    write_sources(
        sources_dir / "sources.csv",
        state["sources"],
        backend=backend,
    )
    persist_memories(
        settings.MEMORIES_DIR,
        state["topic"],
        state["research_notes"],
        state["key_insights"],
        state["reasoning"],
        state["sources"],
        DEFAULT_REPORT_PATH,
        backend=backend,
    )
    return {}
