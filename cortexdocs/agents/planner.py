import json

from langchain_core.runnables import RunnableConfig
import anthropic
from rich.console import Console

from cortexdocs.agents.state import DocPlan, DocPageSpec, PipelineState
from cortexdocs.config import Settings
from cortexdocs.logging_util import accumulate_usage, agent_log

console = Console()

_SYSTEM_PROMPT_PHASE1 = """\
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
  - For the overview (index.md): Start with a "Documentation Sections" table linking to tools/index.md, architecture.md, setup.md, and extending.md (use relative paths from index.md). Then: server purpose, data model (what stores exist and how they differ), functional areas (named groupings of tools, not individual tool tables), typical multi-step usage workflows, architecture notes. Do NOT include per-tool tables or a full tool listing — that is the tools index page's job.
  - For the tools index (tools/index.md): TECHNICAL REFERENCE — one table per functional group listing tool name + one-line description, a "Choosing the right search tool" decision table, a "Choosing the right write tool" decision table, the read-before-write protocol (as a numbered list, not a code block). No server overview prose — that belongs in index.md.

## Output format

Call the create_doc_plan tool with the complete plan. Do not include any explanation outside the tool call.
"""

_SYSTEM_PROMPT_PHASE2 = """\
You are a technical documentation planner for MCP (Model Context Protocol) servers.

You have been given both the server manifest (Phase 1) and a structured research report produced by \
analysing the server's source code (Phase 2). Produce a complete documentation plan.

## Required pages

Phase 1 pages (always included):
1. Overview page  — page_id: "overview", filename: "index.md"
2. Tools index    — page_id: "tools-index", filename: "tools/index.md"
3. One page per tool — page_id: "tool-{tool-name}", filename: "tools/{tool-name}.md"
   where {tool-name} is the tool name with underscores replaced by hyphens, e.g. capture_thought → tools/capture-thought.md

Phase 2 pages (include because research is available):
4. Architecture   — page_id: "architecture", filename: "architecture.md"
5. Setup guide    — page_id: "setup", filename: "setup.md"
6. Extension guide — page_id: "extending", filename: "extending.md"

## Page spec rules

- audience: always "both"
- phase: 1 for protocol-only pages, 2 for pages that require research
- key_points: 3–5 bullet points the writer MUST cover on this page
  - Phase 1 page rules: same as Phase 1 planner (overview must start with a Documentation Sections table linking to all major sections)
  - architecture.md: runtime stack, data stores and schemas, how the MCP layer sits on top, request lifecycle, external services
  - setup.md: prerequisites, environment variables, database setup steps, how to start the server in both stdio and HTTP modes
  - extending.md: how to add a new MCP tool — registration pattern, relevant files, conventions, testing approach

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
    research = state.get("research")
    manifest_json = manifest.model_dump_json(indent=2)
    tool_count = len(manifest.tools)
    phase = 2 if research else 1

    console.print(f"[bold]Planner:[/bold] building doc plan for {tool_count} tools (Phase {phase})...")

    system_prompt = _SYSTEM_PROMPT_PHASE2 if research else _SYSTEM_PROMPT_PHASE1

    # Build message content — manifest always first (cached), research appended if present
    content: list[dict] = [
        {
            "type": "text",
            "text": f"MCP server manifest:\n\n```json\n{manifest_json}\n```",
            "cache_control": {"type": "ephemeral"},
        }
    ]
    if research:
        content.append({
            "type": "text",
            "text": f"Research report:\n\n```json\n{research.model_dump_json(indent=2)}\n```",
            "cache_control": {"type": "ephemeral"},
        })
    content.append({"type": "text", "text": "Create the documentation plan."})

    with agent_log("planner", settings.writer_model, settings.log_dir, f"{tool_count} tools, phase={phase}") as log:
        response = client.messages.create(
            model=settings.writer_model,
            max_tokens=8192,
            system=system_prompt,
            messages=[{"role": "user", "content": content}],
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

    pages_raw = plan_data["pages"]
    # The model occasionally returns the array as a JSON string rather than a parsed list
    if isinstance(pages_raw, str):
        pages_raw = json.loads(pages_raw)
    doc_plan = DocPlan(
        pages=[DocPageSpec(**p) for p in pages_raw]
    )

    console.print(f"[green]✓[/green] Doc plan: {len(doc_plan.pages)} pages")
    for page in doc_plan.pages:
        console.print(f"  [dim]·[/dim] {page.filename}")

    return {
        "doc_plan": doc_plan,
        "current_page_index": 0,
        "token_usage": accumulate_usage(state.get("token_usage", {}), response.usage),
    }
