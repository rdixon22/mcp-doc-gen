import json

import anthropic
from langchain_core.runnables import RunnableConfig
from rich.console import Console

from cortexdocs.agents.state import PipelineState, ResearchOutput
from cortexdocs.config import Settings
from cortexdocs.ingest.models import IngestedRepo
from cortexdocs.logging_util import accumulate_usage, agent_log

console = Console()

_SYSTEM_PROMPT = """\
You are a senior software engineer analysing a codebase to produce structured documentation research.

You will receive:
1. The MCP server manifest (tool names, descriptions, input schemas) — this is the ground truth for what the server exposes.
2. The source files from the repository, each labelled with its relative path and classification.

Your output will be cached and reused by the Writer for every documentation page it produces. \
The Writer cannot see the source files — only your research. Be thorough, especially on `tool_notes`.

Call the submit_research tool with your complete findings. Do not include any explanation outside the tool call.

## Guidelines

- `repo_purpose`: one sentence. What does this server do for its users?
- `architecture_summary`: 3–5 sentences covering the runtime stack, data stores, and how the MCP layer sits on top.
- `tool_notes`: **fill this first** — one entry per tool in the manifest. `implementation_file` is the most relevant source file. \
  `how_it_works` is 2–4 sentences on what the tool does internally — data store access, external services called, \
  any notable business logic. `dependencies` lists external services or libraries the tool relies on.
- `setup_steps`: ordered list of steps a new developer follows to run this server locally. Fill after tool_notes.
- `extension_points`: how a developer would add a new tool — registration pattern, relevant files, conventions. Fill after setup_steps.
- `module_summaries`: one entry per meaningful source file (skip tests and trivial configs). Fill last.
"""

_TOOL_DEF = {
    "name": "submit_research",
    "description": "Output the complete research findings for this repository.",
    "input_schema": {
        "type": "object",
        "properties": {
            "repo_name":            {"type": "string"},
            "repo_purpose":         {"type": "string"},
            "architecture_summary": {"type": "string"},
            "tool_notes": {
                "type": "array",
                "description": "One entry per tool in the manifest. Fill this before module_summaries.",
                "items": {
                    "type": "object",
                    "properties": {
                        "tool_name":            {"type": "string"},
                        "implementation_file":  {"type": "string"},
                        "how_it_works":         {"type": "string"},
                        "dependencies":         {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["tool_name", "implementation_file", "how_it_works", "dependencies"],
                },
            },
            "setup_steps":      {"type": "array", "items": {"type": "string"}},
            "extension_points": {"type": "array", "items": {"type": "string"}},
            "module_summaries": {
                "type": "array",
                "description": "One entry per meaningful source file. Fill after tool_notes.",
                "items": {
                    "type": "object",
                    "properties": {
                        "path":         {"type": "string"},
                        "purpose":      {"type": "string"},
                        "key_exports":  {"type": "array", "items": {"type": "string"}},
                        "dependencies": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["path", "purpose", "key_exports", "dependencies"],
                },
            },
        },
        "required": [
            "repo_name", "repo_purpose", "architecture_summary", "tool_notes",
        ],
    },
}


def _build_repo_content(repo: IngestedRepo) -> str:
    """Serialise the ingested repo into a text block for the researcher prompt."""
    parts: list[str] = [f"Repository root: {repo.root_path}\n"]

    if repo.skipped_files:
        parts.append(
            f"Files omitted (exceeded token budget): {', '.join(repo.skipped_files[:20])}"
            + (f" ... and {len(repo.skipped_files) - 20} more" if len(repo.skipped_files) > 20 else "")
            + "\n"
        )

    for f in repo.files:
        parts.append(f"\n--- FILE: {f.path} [{f.classification}] ---")
        if f.content is None:
            parts.append("(content omitted — file exceeded token budget)")
        else:
            parts.append(f.content)

    return "\n".join(parts)


def researcher_node(state: PipelineState, config: RunnableConfig) -> dict:
    settings: Settings = config["configurable"]["settings"]
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    manifest = state["manifest"]
    repo: IngestedRepo = state["ingested_repo"]

    console.print(f"[bold]Researcher:[/bold] Analysing {repo.total_files} files...")

    manifest_json = manifest.model_dump_json(indent=2)
    repo_content = _build_repo_content(repo)

    with agent_log(
        "researcher", settings.researcher_model, settings.log_dir,
        f"{repo.total_files} files, {len(manifest.tools)} tools",
    ) as log:
        response = client.messages.create(
            model=settings.researcher_model,
            max_tokens=16000,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            # Manifest cached — same block used by every Writer call
                            "text": f"MCP server manifest:\n\n```json\n{manifest_json}\n```",
                            "cache_control": {"type": "ephemeral"},
                        },
                        {
                            "type": "text",
                            # Repo content also cached — expensive on first run, free on re-runs
                            "text": f"Repository source files:\n\n{repo_content}",
                            "cache_control": {"type": "ephemeral"},
                        },
                    ],
                }
            ],
            tools=[_TOOL_DEF],
            tool_choice={"type": "tool", "name": "submit_research"},
        )

        tool_block = next(b for b in response.content if b.type == "tool_use")
        data = tool_block.input
        log["input_tokens"] = response.usage.input_tokens
        log["output_tokens"] = response.usage.output_tokens
        log["cache_read_tokens"] = getattr(response.usage, "cache_read_input_tokens", 0)
        log["cache_write_tokens"] = getattr(response.usage, "cache_creation_input_tokens", 0)
        log["full_output"] = json.dumps(data)

    research = ResearchOutput(**data)

    if not research.tool_notes:
        console.print("[yellow]Warning:[/yellow] Researcher returned no tool_notes — model may have truncated output. Phase 2 tool pages will lack implementation context.")
    if not research.setup_steps:
        console.print("[yellow]Warning:[/yellow] Researcher returned no setup_steps.")
    if not research.extension_points:
        console.print("[yellow]Warning:[/yellow] Researcher returned no extension_points.")

    # Persist for --from-stage write re-runs
    research_path = settings.output_dir / "research.json"
    research_path.write_text(research.model_dump_json(indent=2), encoding="utf-8")

    console.print(
        f"[green]✓[/green] Research complete — "
        f"{len(research.module_summaries)} modules, "
        f"{len(research.tool_notes)} tool notes"
    )
    console.print(f"[dim]Research saved to {research_path}[/dim]")

    return {
        "research": research,
        "token_usage": accumulate_usage(state.get("token_usage", {}), response.usage),
    }
