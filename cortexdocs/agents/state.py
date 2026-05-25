from typing import Any, Literal, TypedDict

from pydantic import BaseModel

from cortexdocs.discovery.models import MCPServerManifest


# ---------------------------------------------------------------------------
# Phase 2 — Research output models (produced by researcher_node)
# ---------------------------------------------------------------------------

class ModuleSummary(BaseModel):
    path: str
    purpose: str
    key_exports: list[str]
    dependencies: list[str]


class ToolImplementationNote(BaseModel):
    tool_name: str              # matches MCPToolDef.name
    implementation_file: str
    how_it_works: str           # 2–4 sentence prose
    dependencies: list[str]     # external services, libs


class ResearchOutput(BaseModel):
    repo_name: str
    repo_purpose: str
    architecture_summary: str
    module_summaries: list[ModuleSummary] = []
    tool_notes: list[ToolImplementationNote] = []
    setup_steps: list[str] = []
    extension_points: list[str] = []


# ---------------------------------------------------------------------------
# Pipeline models
# ---------------------------------------------------------------------------

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
    # ingested_repo typed as Any to avoid importing ingest.models here
    ingested_repo: Any | None
    research: ResearchOutput | None
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
