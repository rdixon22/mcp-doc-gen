from typing import Literal

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from cortexdocs.agents.state import PipelineState
from cortexdocs.config import Settings


def build_graph(settings: Settings, checkpointer: SqliteSaver):
    """Build and compile the documentation pipeline StateGraph."""
    from cortexdocs.agents.planner import planner_node
    from cortexdocs.agents.reviewer import reviewer_node
    from cortexdocs.agents.writer import writer_node
    from cortexdocs.render.human_site import render_node

    builder = StateGraph(PipelineState)

    # Phase 2 nodes — only wired when a repo path is provided
    if settings.repo_path:
        from cortexdocs.ingest.walker import ingest_node
        from cortexdocs.agents.researcher import researcher_node

        builder.add_node("ingest", ingest_node)
        builder.add_node("researcher", researcher_node)
        builder.add_edge(START, "ingest")
        builder.add_edge("ingest", "researcher")
        builder.add_edge("researcher", "planner")
    else:
        builder.add_edge(START, "planner")

    builder.add_node("planner", planner_node)
    builder.add_node("writer", writer_node)
    builder.add_node("reviewer", reviewer_node)
    builder.add_node("render", render_node)

    builder.add_edge("planner", "writer")
    builder.add_edge("writer", "reviewer")
    builder.add_conditional_edges(
        "reviewer",
        route_reviewer,
        {"writer": "writer", "render": "render"},
    )
    builder.add_edge("render", END)

    return builder.compile(checkpointer=checkpointer)


def route_reviewer(state: PipelineState) -> Literal["writer", "render"]:
    """After the reviewer runs, decide whether to write the next page or render.

    The reviewer_node is responsible for advancing current_page_index when a page
    is finalized (approved or revision-capped). This function just checks whether
    there are more pages left.
    """
    doc_plan = state["doc_plan"]
    if doc_plan is None:
        return "render"
    if state["current_page_index"] >= len(doc_plan.pages):
        return "render"
    return "writer"


def initial_state(manifest, settings: Settings) -> PipelineState:
    """Construct the starting PipelineState for a fresh pipeline run."""
    return PipelineState(
        manifest=manifest,
        ingested_repo=None,
        research=None,
        repo_enriched=bool(settings.repo_path),
        doc_plan=None,
        pages=[],
        current_page_index=0,
        revision_counts={},
        approved_pages=[],
        errors=[],
        token_usage={},
    )
