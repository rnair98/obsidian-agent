from app.core.paths import DEFAULT_REPORT_PATH
from app.core.settings import settings
from app.engine.artifacts import CsvSourceStore, MarkdownMemoryStore
from app.engine.backends import artifacts_backend
from app.engine.schema import ResearchState


def persist_artifacts(state: ResearchState) -> dict:
    """Side-effect node: write sources.csv and memory markdown.

    Returns an empty delta — LangGraph merges this with the existing state,
    so there's no need to echo every field back through the checkpointer.
    """
    backend = artifacts_backend()
    CsvSourceStore(backend, settings.OUTPUT_DIR).write(state["sources"])
    MarkdownMemoryStore(backend, settings.MEMORIES_DIR).write_run(
        topic=state["topic"],
        notes=state["research_notes"],
        insights=state["key_insights"],
        reasoning=state["reasoning"],
        sources=state["sources"],
        report_path=DEFAULT_REPORT_PATH,
    )
    return {}
