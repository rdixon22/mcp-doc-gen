import json

import anthropic
from langchain_core.runnables import RunnableConfig
from rich.console import Console

from cortexdocs.agents.state import DocPage, PipelineState
from cortexdocs.config import Settings
from cortexdocs.logging_util import accumulate_usage, agent_log

console = Console()

_SYSTEM_PROMPT = """\
You are a technical documentation reviewer for an MCP (Model Context Protocol) server.

Review the submitted documentation page against the provided ground truth sources.
Then call the submit_review tool with your verdict.

## Checklist — flag issues under "revise", not "approved"

1. **Parameter accuracy** — every parameter in the tool's inputSchema is documented with the correct name, type, required/optional status, and description. No extra parameters invented.
2. **Tool name and description** — match the manifest exactly. No paraphrasing that changes meaning.
3. **Return value** — described, even if brief.
4. **Usage example** — at least one concrete example present for tool pages.
5. **Frontmatter validity** — all required fields present: title, description, audience, topics, mcp_tools, doc_phase, reviewed, generated_at, model.
6. **No hallucination** — no claims about implementation, internals, or behaviour that cannot be verified from the provided ground truth sources.
7. **No wrapping** — the page must NOT be enclosed in triple backticks or any outer code fence. The frontmatter `---` must be the very first line.
8. **Implementation accuracy** (Phase 2 pages only) — if a research note is provided, any implementation claims (data stores used, external services called, file paths mentioned) must not contradict it.

## notes field

When status is "revise": list the specific issues as bullet points. Be concrete — name the field or section that is wrong. Max 150 words.
When status is "approved": omit notes or leave it empty.
"""

_TOOL_DEF = {
    "name": "submit_review",
    "description": "Submit the review verdict for this documentation page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["approved", "revise"],
                "description": "approved = page is correct and complete; revise = specific issues found",
            },
            "notes": {
                "type": "string",
                "description": "Required when status is revise. Bullet-point list of specific issues to fix.",
            },
        },
        "required": ["status"],
    },
}


def reviewer_node(state: PipelineState, config: RunnableConfig) -> dict:
    settings: Settings = config["configurable"]["settings"]
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    current_index = state["current_page_index"]
    doc_plan = state["doc_plan"]
    pages = list(state["pages"])
    current_page = pages[current_index]
    spec = current_page.spec
    manifest = state["manifest"]
    revision_counts = dict(state["revision_counts"])
    approved_pages = list(state["approved_pages"])

    current_revisions = revision_counts.get(spec.page_id, 0)

    # Hard cap — ship as partial without an LLM call
    if current_revisions >= settings.max_revision_rounds:
        console.print(f"  [yellow]⚠[/yellow]  {spec.filename}: revision cap reached, shipping as partial")
        final_page = current_page.model_copy(update={"review_status": "partial"})
        pages[current_index] = final_page
        approved_pages.append(final_page)
        _save_page(final_page, settings)
        return {
            "pages": pages,
            "approved_pages": approved_pages,
            "current_page_index": current_index + 1,
            "revision_counts": revision_counts,
        }

    # Build review context: manifest tool def (always for tool pages) + research note (Phase 2)
    research = state.get("research")
    tool_context = ""
    if spec.page_id.startswith("tool-"):
        tool_name = spec.page_id[len("tool-"):].replace("-", "_")
        tool = next((t for t in manifest.tools if t.name == tool_name), None)
        if tool:
            tool_context = (
                f"Tool definition from manifest (authoritative ground truth):\n"
                f"```json\n{json.dumps(tool.model_dump(), indent=2)}\n```\n\n"
            )
        if research:
            note = next((n for n in research.tool_notes if n.tool_name == tool_name), None)
            if note:
                tool_context += (
                    f"Implementation note from repo research:\n"
                    f"```json\n{json.dumps(note.model_dump(), indent=2)}\n```\n\n"
                )

    review_prompt = (
        f"{tool_context}"
        f"Documentation page to review:\n\n"
        f"{current_page.content}"
    )

    console.print(f"[bold]Reviewer:[/bold] Reviewing [cyan]{spec.filename}[/cyan]...")

    with agent_log(
        "reviewer", settings.reviewer_model, settings.log_dir,
        f"{spec.filename} rev={current_revisions}",
    ) as log:
        response = client.messages.create(
            model=settings.reviewer_model,
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": review_prompt}],
            tools=[_TOOL_DEF],
            tool_choice={"type": "tool", "name": "submit_review"},
        )

        tool_block = next(b for b in response.content if b.type == "tool_use")
        review = tool_block.input
        log["input_tokens"] = response.usage.input_tokens
        log["output_tokens"] = response.usage.output_tokens
        log["full_output"] = json.dumps(review)

    status = review.get("status", "approved")
    notes = review.get("notes") or None

    token_usage = accumulate_usage(state.get("token_usage", {}), response.usage)

    if status == "revise":
        revision_counts[spec.page_id] = current_revisions + 1
        revised_page = current_page.model_copy(
            update={"review_status": "revise", "reviewer_notes": notes}
        )
        pages[current_index] = revised_page
        notes_preview = next(iter((notes or "").splitlines()), "")[:80]
        console.print(
            f"  [yellow]↺[/yellow]  {spec.filename}: revision {revision_counts[spec.page_id]}"
            f"/{settings.max_revision_rounds} — {notes_preview}"
        )
        return {
            "pages": pages,
            "revision_counts": revision_counts,
            "token_usage": token_usage,
        }

    # Approved — finalise and advance
    approved_page = current_page.model_copy(
        update={"review_status": "approved", "reviewer_notes": None}
    )
    pages[current_index] = approved_page
    approved_pages.append(approved_page)
    _save_page(approved_page, settings)
    console.print(f"  [green]✓[/green]  {spec.filename}")

    return {
        "pages": pages,
        "approved_pages": approved_pages,
        "current_page_index": current_index + 1,
        "revision_counts": revision_counts,
        "token_usage": token_usage,
    }


def _save_page(page: DocPage, settings: Settings) -> None:
    """Persist an approved page to output/pages/ for auditability."""
    dest = settings.output_dir / "pages" / page.spec.filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(page.content, encoding="utf-8")
