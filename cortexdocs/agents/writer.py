import json
from datetime import datetime, timezone

import anthropic
from langchain_core.runnables import RunnableConfig
from rich.console import Console

from cortexdocs.agents.state import DocPage, DocPageSpec, PipelineState
from cortexdocs.config import Settings
from cortexdocs.logging_util import accumulate_usage, agent_log

console = Console()

_SYSTEM_PROMPT = """\
You are a technical writer producing documentation for an MCP (Model Context Protocol) server.

You write for two audiences at once:
1. **Human developers** reading rendered web pages — they want clear prose, examples, and context.
2. **AI agents** consuming the docs programmatically — they need precise parameter specs, exact names, and structured information they can parse reliably.

Write for both. Use markdown. Be complete and precise. Cut filler.

## Output format

Your response IS the raw file content. Output rules:
- Start immediately with the `---` frontmatter fence — no preamble, no explanation.
- Do NOT wrap your output in triple backticks, code fences, or any outer container. The response itself is the page.
- End after the last line of content — no trailing explanation.

## Style rules

- Cover every parameter: name, type, required/optional, description, default value if any.
- For tool pages: always include a Parameters section (markdown table), a Returns section, and at least one Usage example in a code block.
- For the overview page (index.md): write CONCEPTUAL content — what the server does, its data model, functional areas (named groups of tools, no per-tool tables), multi-step usage workflows, architecture notes. Do not reproduce the full tool listing; the tools index page handles that.
- For the tools index page (tools/index.md): write a TECHNICAL REFERENCE — one table per functional group with tool name + one-line description, "Choosing the right search/write tool" decision tables, and any required protocol notes (e.g. read-before-write as a numbered list). No server overview prose.
- Links to tool pages must use **relative paths** from the file's own location. From `index.md` (root): `[capture_thought](tools/capture-thought.md)`. From `tools/index.md` (already inside `tools/`): `[capture_thought](capture-thought.md)` — no `tools/` prefix. Always use hyphens (not underscores) in filenames.
- No "In this document..." intros. No "Conclusion" sections.

## Required frontmatter

Every page MUST begin with this YAML frontmatter block:

---
title: "<page title>"
description: "<one sentence description>"
audience: both
topics: [keyword1, keyword2, keyword3]
mcp_tools: [tool_name1, tool_name2]
doc_phase: 1
reviewed: pending
generated_at: <provided in the instructions>
model: <provided in the instructions>
---
"""


def _tool_for_page(spec: DocPageSpec, manifest) -> dict | None:
    """Return the manifest tool dict for tool pages, None for other pages."""
    if not spec.page_id.startswith("tool-"):
        return None
    tool_name = spec.page_id[len("tool-"):].replace("-", "_")
    tool = next((t for t in manifest.tools if t.name == tool_name), None)
    return tool.model_dump() if tool else None


def writer_node(state: PipelineState, config: RunnableConfig) -> dict:
    settings: Settings = config["configurable"]["settings"]
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    manifest = state["manifest"]
    doc_plan = state["doc_plan"]
    current_index = state["current_page_index"]
    spec = doc_plan.pages[current_index]

    pages = list(state["pages"])
    is_revision = current_index < len(pages)
    reviewer_notes = pages[current_index].reviewer_notes if is_revision else None
    revision_count = state["revision_counts"].get(spec.page_id, 0)

    verb = "Revising" if is_revision else "Writing"
    console.print(
        f"[bold]Writer:[/bold] {verb} [cyan]{spec.filename}[/cyan] "
        f"({current_index + 1}/{len(doc_plan.pages)})"
        + (f" [yellow]rev {revision_count}[/yellow]" if is_revision else "")
    )

    # Build tool-specific context for accurate parameter coverage
    tool_def = _tool_for_page(spec, manifest)
    tool_context = ""
    if tool_def:
        tool_context = (
            f"\n\nRelevant tool definition (authoritative — match parameter names exactly):\n"
            f"```json\n{json.dumps(tool_def, indent=2)}\n```\n"
        )

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    instructions = (
        f"Write the following documentation page.\n\n"
        f"**Page spec:**\n```json\n{spec.model_dump_json(indent=2)}\n```\n"
        f"{tool_context}\n"
        f"Use `generated_at: {now}` and `model: {settings.writer_model}` in the frontmatter.\n"
    )

    if reviewer_notes:
        instructions += (
            f"\n**Reviewer's notes from the previous attempt — fix all of these:**\n"
            f"{reviewer_notes}\n"
        )

    instructions += "\nProduce the complete page now."

    manifest_json = manifest.model_dump_json(indent=2)

    with agent_log(
        "writer", settings.writer_model, settings.log_dir,
        f"{spec.filename} rev={revision_count}",
    ) as log:
        response = client.messages.create(
            model=settings.writer_model,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            # Manifest is identical for every writer call — cache it
                            "text": f"MCP server manifest:\n\n```json\n{manifest_json}\n```",
                            "cache_control": {"type": "ephemeral"},
                        },
                        {
                            "type": "text",
                            "text": instructions,
                        },
                    ],
                }
            ],
        )

        content = response.content[0].text
        log["input_tokens"] = response.usage.input_tokens
        log["output_tokens"] = response.usage.output_tokens
        log["cache_read_tokens"] = getattr(response.usage, "cache_read_input_tokens", 0)
        log["cache_write_tokens"] = getattr(response.usage, "cache_creation_input_tokens", 0)
        log["output_preview"] = content[:300]

    new_page = DocPage(
        spec=spec,
        content=content,
        revision_count=revision_count,
        review_status="pending",
        reviewer_notes=None,
    )

    if current_index >= len(pages):
        pages.append(new_page)
    else:
        pages[current_index] = new_page

    return {
        "pages": pages,
        "token_usage": accumulate_usage(state.get("token_usage", {}), response.usage),
    }
