from app.core.paths import DEFAULT_REPORT_PATH
from app.core.settings import settings
from app.engine.backends import get_filesystem_backend
from app.engine.schema import ResearchState
from app.engine.tools.io import persist_memories, write_sources


def persist_artifacts(state: ResearchState) -> ResearchState:
    filesystem_backend = get_filesystem_backend(
        backend_type=settings.filesystem.backend_type,
        base_path=settings.filesystem.base_path,
    )
    sources_dir = settings.OUTPUT_DIR
    write_sources(
        sources_dir / "sources.csv",
        state.sources,
        filesystem_backend=filesystem_backend,
    )
    persist_memories(
        settings.MEMORIES_DIR,
        state.topic,
        state.research_notes,
        state.key_insights,
        state.reasoning,
        state.sources,
        DEFAULT_REPORT_PATH,
        filesystem_backend=filesystem_backend,
    )
    return state
