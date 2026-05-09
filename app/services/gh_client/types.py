from datetime import datetime
from pathlib import Path

from pydantic import BaseModel


class SnapshotResult(BaseModel):
    repo_name: str
    commit_sha: str
    requested_ref: str
    path: Path
    created_at: datetime
    skipped: bool
