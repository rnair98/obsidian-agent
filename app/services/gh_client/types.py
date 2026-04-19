from datetime import datetime
from pathlib import Path
from typing import TypedDict


class SnapshotResult(TypedDict):
    repo_name: str
    commit_sha: str
    requested_ref: str
    path: Path
    created_at: datetime
    skipped: bool
