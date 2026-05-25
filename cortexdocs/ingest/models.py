from typing import Literal

from pydantic import BaseModel


class SourceFile(BaseModel):
    path: str                   # relative to repo root
    classification: Literal["mcp_registration", "handler", "config", "test", "util", "docs", "other"]
    size_bytes: int
    content: str | None         # None when file exceeds token budget


class IngestedRepo(BaseModel):
    root_path: str
    files: list[SourceFile]
    total_files: int
    skipped_files: list[str]    # paths omitted due to token budget
