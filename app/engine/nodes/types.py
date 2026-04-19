from enum import StrEnum


class Workflow(StrEnum):
    RESEARCHER = "researcher"
    SUMMARIZER = "summarizer"
    ZETTELKASTEN = "zettelkasten"
    PERSIST = "persist"
    RESEARCH = "research"
