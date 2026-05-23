import json

from langchain_core.runnables import RunnableConfig
import anthropic
from rich.console import Console

from cortexdocs.agents.state import DocPlan, DocPageSpec, PipelineState
from cortexdocs.config import Settings
from cortexdocs.logging_util import accumulate_usage, agent_log

console = Console()

_SYSTEM_PROMPT = """\
You are a technical documentation planner for MCP (Model Context Protocol) servers.

Given a server manifest, produce a complete documentation plan as a structured list of pages.

## Required pages (Phase 1 — protocol only)

Always include these pages, in this order:
1. Overview page  — page_id: "overview", filename: "index.md"
2. Tools index    — page_id: "tools-index", filename: "tools/index.md"
3. One page per tool — page_id: "tool-{tool-name}", filename: "tools/{tool-name}.md"
   where {tool-name} is the tool name with underscores replaced by hyphens.

## Page spec rules

- audience: always "both" for Phase 1 (optimised for both human readers and AI agents)
- phase: always 1
- key_points: 3–5 bullet points the writer MUST cover on this page
  - For tool pages: what the tool does, every parameter (name, type, required/optional, description), return value, at least one concrete usage example
  - For the overview (index.md): CONCEPTUAL content only — server purpose, data model (what stores exist and how they differ), functional areas (named groupings of tools, not individual tool tables), typical multi-step usage workflows, architecture notes. Do NOT include per-tool tables or a full tool listing — that is the tools index page's job.
  - For the tools index (tools/index.md): TECHNICAL REFERENCE — one table per functional group listing tool name + one-line description, a "Choosing the right search tool" decision table, a "Choosing the right write tool" decision table, the read-before-write protocol (as a numbered list, not a code block). No server overview prose — that belongs in index.md.

## Output format

Call the create_doc_plan tool with the complete plan. Do not include any explanation outside the tool call.
"""

_TOOL_DEF = {
    "name": "create_doc_plan",
    "description": "Output the complete documentation plan for this MCP server.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "page_id":    {"type": "string"},
                        "title":      {"type": "string"},
                        "filename":   {"type": "string"},
                        "audience":   {"type": "string", "enum": ["human", "both"]},
                        "phase":      {"type": "integer", "enum": [1, 2]},
                        "key_points": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["page_id", "title", "filename", "audience", "phase", "key_points"],
                },
            }
        },
        "required": ["pages"],
    },
}


def planner_node(state: PipelineState, config: RunnableConfig) -> dict:
    settings: Settings = config["configurable"]["settings"]
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    manifest = state["manifest"]
    manifest_json = manifest.model_dump_json(indent=2)
    tool_count = len(manifest.tools)

    console.print(f"[bold]Planner:[/bold] building doc plan for {tool_count} tools...")

    with agent_log("planner", settings.writer_model, settings.log_dir, f"{tool_count} tools, {manifest.server_name}") as log:
        response = client.messages.create(
            model=settings.writer_model,
            max_tokens=8192,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Here is the MCP server manifest:\n\n```json\n{manifest_json}\n```\n\nCreate the documentation plan.",
                            # Cache the manifest — it will be reused by every Writer call too
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            ],
            tools=[_TOOL_DEF],
            tool_choice={"type": "tool", "name": "create_doc_plan"},
        )

        log["input_tokens"] = response.usage.input_tokens
        log["output_tokens"] = response.usage.output_tokens
        log["cache_read_tokens"] = getattr(response.usage, "cache_read_input_tokens", 0)
        log["cache_write_tokens"] = getattr(response.usage, "cache_creation_input_tokens", 0)

        # Extract tool call arguments
        tool_block = next(b for b in response.content if b.type == "tool_use")
        plan_data = tool_block.input
        log["full_output"] = json.dumps(plan_data)

    doc_plan = DocPlan(
        pages=[DocPageSpec(**p) for p in plan_data["pages"]]
    )

    console.print(f"[green]✓[/green] Doc plan: {len(doc_plan.pages)} pages")
    for page in doc_plan.pages:
        console.print(f"  [dim]·[/dim] {page.filename}")

    return {
        "doc_plan": doc_plan,
        "current_page_index": 0,
        "token_usage": accumulate_usage(state.get("token_usage", {}), response.usage),
    }
