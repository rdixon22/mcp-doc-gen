from langchain_core.runnables import RunnableConfig
from cortexdocs.agents.state import PipelineState


def researcher_node(state: PipelineState, config: RunnableConfig) -> dict:
    """Analyse the repo and produce ResearchOutput. Implemented in Day 3."""
    raise NotImplementedError("researcher_node — Day 3")
