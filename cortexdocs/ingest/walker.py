from langchain_core.runnables import RunnableConfig
from cortexdocs.agents.state import PipelineState


def ingest_node(state: PipelineState, config: RunnableConfig) -> dict:
    """Walk the repo and classify source files. Implemented in Day 3."""
    raise NotImplementedError("ingest_node — Day 3")
