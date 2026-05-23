from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

from cortexdocs.discovery.models import MCPServerManifest


class DocPageSpec(BaseModel):
    page_id: str              # slug, e.g. "tool-capture-thought"
    title: str                # human-readable, e.g. "capture_thought"
    filename: str             # relative path, e.g. "tools/capture-thought.md"
    audience: Literal["human", "both"]
    phase: Literal[1, 2]
    key_points: list[str]


class DocPlan(BaseModel):
    pages: list[DocPageSpec]


class DocPage(BaseModel):
    spec: DocPageSpec
    content: str = ""
    revision_count: int = 0
    review_status: Literal["pending", "revise", "approved", "partial"] = "pending"
    reviewer_notes: str | None = None


class PipelineState(TypedDict):
    # Phase 1 (always present)
    manifest: MCPServerManifest

    # Phase 2 (None when running Phase 1 only)
    # Typed as Any to avoid circular imports before ingest/agents modules exist
    ingested_repo: Any | None
    research: Any | None
    repo_enriched: bool

    # Writer / reviewer shared state
    doc_plan: DocPlan | None
    pages: list[DocPage]
    current_page_index: int
    revision_counts: dict[str, int]   # page_id → number of revisions sent so far
    approved_pages: list[DocPage]

    # Observability
    errors: list[str]
    token_usage: dict[str, int]       # cumulative: input, output, cache_read, cache_write
