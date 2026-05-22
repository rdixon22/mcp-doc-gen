# CortexDocs — Implementation Plan

**Status:** Draft v0.1
**Date:** 2026-05-22
**Based on:** [BRIEF.md](BRIEF.md) · [ARCHITECTURE.md](ARCHITECTURE.md)

---

## Prerequisites (before Day 1 begins)

- [ ] Python 3.11+ available (`python3 --version`)
- [ ] `uv` installed for dependency management (`pip install uv`)
- [ ] Anthropic API key in hand
- [ ] Cortex repo at `~/Documents/dev/ai/ai-local-test` has `npm install` run and builds cleanly
- [ ] Verify Cortex MCP stdio works: `cd ~/Documents/dev/ai/ai-local-test && npx tsx src/server/mcp-stdio.ts` — should start without errors
- [ ] Write the 15 eval questions **now**, before looking at any generated output (see Day 4 section for the question set)

---

## Shippable checkpoints

The plan is structured so each day ends with something independently demoable:

| End of day | What exists | Demo statement |
|---|---|---|
| Day 1 | `output/manifest.json` | "It connects to any MCP server and extracts the full tool catalog in seconds" |
| Day 2 | Phase 1 docs site (live URL) | "From a running MCP server to a browsable docs site — no source code needed" |
| Day 3 | Phase 1+2 docs site (enriched) | "Add the repo and it writes architecture, setup, and extension guides too" |
| Day 4 | Eval report + polished README | "Here's what the two approaches answer differently, and why it matters" |

Day 2 is the **minimum shippable artifact** for the interview. If Days 3–4 slip, Day 2 still demonstrates the thesis.

---

## Day 1 — Project setup + Phase 1 discovery

**Goal:** Running `python3 -m cortexdocs generate --server-cmd "..."` produces `output/manifest.json` containing all 16 Cortex tools.

### Morning: Project scaffold

**1. `pyproject.toml`**
```toml
[project]
name = "cortexdocs"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.49.0",
    "mcp>=1.8.0",
    "langgraph>=0.2.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "typer>=0.12.0",
    "mkdocs-material>=9.5",
    "tiktoken>=0.7.0",
    "rich>=13.0",
]

[project.scripts]
cortexdocs = "cortexdocs.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Run `uv sync` to create the virtualenv and install deps.

**2. Package skeleton** — create all `__init__.py` files and the directory structure from ARCHITECTURE.md. Empty files are fine; the goal is importable modules.

**3. `cortexdocs/config.py`** — implement the full `Settings` class using `pydantic-settings`. Read from `.env`. Validate that at least one of `server_cmd` / `server_url` is set.

**4. `cortexdocs/cli.py`** — `typer` app with a single `generate` command that accepts `--server-cmd`, `--server-url`, `--server-cmd-cwd`, `--repo`, `--no-eval`, `--from-stage`. For now, all it does is load config and print it. This is the entry point for everything.

**5. `.env.example`**
```
ANTHROPIC_API_KEY=sk-ant-...
SERVER_CMD=npx tsx src/server/mcp-stdio.ts
SERVER_CMD_CWD=/Users/you/Documents/dev/ai/ai-local-test
REPO_PATH=/Users/you/Documents/dev/ai/ai-local-test
```

**6. `Makefile`**
```makefile
generate:
    python3 -m cortexdocs generate

generate-phase1:
    python3 -m cortexdocs generate --no-repo

serve:
    python3 -m cortexdocs serve

eval:
    python3 -m cortexdocs eval

deploy:
    mkdocs gh-deploy --config-file output/mkdocs.yml

.PHONY: generate generate-phase1 serve eval deploy
```

---

### Afternoon: MCP discovery

**7. `cortexdocs/discovery/models.py`** — implement `MCPToolParam`, `MCPToolDef`, `MCPServerManifest` Pydantic models exactly as specified in ARCHITECTURE.md.

**8. `cortexdocs/discovery/mcp_client.py`** — implement `async def discover(config: Settings) -> MCPServerManifest`.

Key implementation notes:
- Use `mcp.client.session.ClientSession` with either `mcp.client.stdio.StdioClientTransport` or `mcp.client.streamablehttp.StreamableHTTPClientTransport`
- The stdio transport takes `command` and `args` separately — split `config.server_cmd` on spaces to extract the executable and args list
- Wrap `list_resources()` and `list_prompts()` in `try/except` — not all servers implement these; return empty lists on `NotImplementedError`
- Save the raw manifest to `output/manifest.json` immediately after discovery (before any LLM work)

**9. Wire discovery into `cli.py`** — `generate` command calls `asyncio.run(discover(config))`, prints a summary (`Found N tools: tool1, tool2, ...`), and saves `manifest.json`.

**Done criteria for Day 1:**
```bash
python3 -m cortexdocs generate --server-cmd "npx tsx src/server/mcp-stdio.ts" \
  --server-cmd-cwd ~/Documents/dev/ai/ai-local-test
# → output/manifest.json exists
# → contains all 16 tools with names, descriptions, and inputSchema
# → summary printed to terminal
```

**Verify** by opening `output/manifest.json` and checking a few tools match what's in `routes/mcp.ts`.

---

## Day 2 — LangGraph pipeline + Phase 1 docs end-to-end

**Goal:** Running the full generate command produces a browsable MkDocs site with tool reference pages, deployed to a live URL.

### Morning: LangGraph graph + Planner

**10. `cortexdocs/agents/state.py`** — implement `PipelineState` TypedDict, `DocPageSpec`, `DocPlan`, `DocPage` models.

**11. `cortexdocs/agents/graph.py`** — set up the `StateGraph` skeleton:
```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

def build_graph(config: Settings) -> CompiledGraph:
    builder = StateGraph(PipelineState)
    builder.add_node("planner", planner_node)
    builder.add_node("writer", writer_node)
    builder.add_node("reviewer", reviewer_node)
    builder.add_node("render", render_node)

    builder.add_edge(START, "planner")
    builder.add_edge("planner", "writer")
    builder.add_conditional_edges("reviewer", route_reviewer)
    builder.add_edge("render", END)

    memory = SqliteSaver.from_conn_string("output/checkpoints.db")
    return builder.compile(checkpointer=memory)
```

The `route_reviewer` function returns `"writer"` (revise), `"writer_next"` (approved, next page), or `"render"` (all pages done). Use `Send` API for the writer loop if LangGraph version supports it; otherwise manage `current_page_index` in state.

**12. `cortexdocs/logging_util.py`** — implement the log writer. Simple context manager that records `agent`, `model`, timestamps, token counts, input/output summaries, and full I/O to `logs/<timestamp>_<agent>.json`.

**13. `cortexdocs/agents/planner.py`** — `planner_node(state, config)`:
- Input: `state["manifest"]`
- Prompt: give the model the manifest as JSON + a system prompt describing the doc structure we want
- Output: `DocPlan` using structured output (tool use or `response_format`)
- For Phase 1 only: plan includes overview page, per-tool pages (one per tool), and a tools index page. No architecture/setup/extension pages yet.
- Mark all pages `phase: 1`

### Afternoon: Writer + Reviewer + Render

**14. `cortexdocs/agents/writer.py`** — `writer_node(state, config)`:
- Gets current page from `state["doc_plan"].pages[state["current_page_index"]]`
- Builds prompt: system = writer instructions + frontmatter schema; user = manifest (cached block) + page spec + optional reviewer notes
- **Prompt caching:** wrap the manifest JSON block with `{"type": "text", "text": ..., "cache_control": {"type": "ephemeral"}}` — this is the block that will be cached across all page writes
- Returns full markdown with YAML frontmatter

**15. `cortexdocs/agents/reviewer.py`** — `reviewer_node(state, config)`:
- Input: current page content + relevant tool definitions from the manifest
- System prompt checklist: tool names/descriptions match manifest exactly; parameter names and types match `raw_input_schema`; frontmatter valid
- Output: structured `{"status": "approved" | "revise", "notes": str | None}`
- Increment `revision_counts[page_id]`; if >= 2, force `status = "approved"` with a flag in `reviewer_notes`

**16. `cortexdocs/render/machine_artifacts.py`** — implement:
- `write_api_json(manifest, approved_pages, output_dir)` — serialize manifest with `doc_page` links added
- `write_llms_txt(manifest, approved_pages, output_dir)` — generate table of contents
- `write_llms_full_txt(approved_pages, output_dir)` — concatenate pages, strip frontmatter

**17. `cortexdocs/render/human_site.py`** — implement:
- Copy approved pages to `output/site_src/docs/`
- Write `output/mkdocs.yml` from template (server name from manifest as site title, Material theme, nav auto-generated from page filenames)
- Call `mkdocs build --config-file output/mkdocs.yml`

**18. Wire everything into `graph.py`** and update `cli.py` to call `graph.invoke(initial_state)`.

**Done criteria for Day 2:**
```bash
python3 -m cortexdocs generate \
  --server-cmd "npx tsx src/server/mcp-stdio.ts" \
  --server-cmd-cwd ~/Documents/dev/ai/ai-local-test
# → output/manifest.json  (from Day 1)
# → output/pages/*.md     (one per tool + overview + index)
# → output/site/          (rendered HTML)
# → output/llms.txt
# → output/api.json
# → logs/*.json           (one per agent call)
```

Run `python3 -m cortexdocs serve` and verify the site looks reasonable in a browser. Check one tool page against the manifest to confirm accuracy.

**Then deploy:**
```bash
make deploy
# → live URL on GitHub Pages
```

This is the **Option A shippable.** Commit and tag it: `git tag v0.1-phase1`.

---

## Day 3 — Phase 2 repo enrichment + complete docs

**Goal:** Adding `--repo` to the generate command produces richer pages plus architecture, setup, and extension guides.

### Morning: Ingest + Researcher

**19. `cortexdocs/ingest/models.py`** — implement `SourceFile`, `IngestedRepo`.

**20. `cortexdocs/ingest/walker.py`** — implement `walk_repo(repo_path, token_budget) -> IngestedRepo`:
- `os.walk` with skip list (`.git`, `node_modules`, `__pycache__`, `dist`, `build`, `*.lock`)
- Classify each file (classification rules from ARCHITECTURE.md)
- Count tokens with `tiktoken` (use `cl100k_base` encoder, close enough for any Claude model)
- If a file's tokens push the budget over, store `content = None` and note it as skipped
- Files below threshold: read full content; files above: store `None` (Researcher will receive a note about them)

**21. `cortexdocs/agents/researcher.py`** — `researcher_node(state, config)`:
- Input: `state["manifest"]` + `state["ingested_repo"]`
- Prompt strategy:
  - System: researcher role + output schema
  - User message 1: manifest JSON (cached block — same block as Writer uses)
  - User message 2: each `SourceFile` as a separate content block, large files noted as "content omitted (too large)" with just path and classification
- Output: `ResearchOutput` with `tool_notes` entries keyed to `manifest.tools[*].name`
- Save to `output/research.json`

**22. Add `ingest_node` and `researcher_node` to `graph.py`**:
```python
if config.repo_path:
    builder.add_node("ingest", ingest_node)
    builder.add_node("researcher", researcher_node)
    builder.add_edge(START, "ingest")
    builder.add_edge("ingest", "researcher")
    builder.add_edge("researcher", "planner")
else:
    builder.add_edge(START, "planner")
```

### Afternoon: Enriched planner + complete artifacts

**23. Update `planner_node`** — when `state["research"]` is present, include `phase: 2` pages in the plan: `architecture.md`, `setup.md`, `extending.md`. Update Writer prompt to use `ResearchOutput` when available.

**24. Update `writer_node`** — add a second cached block for `ResearchOutput` JSON alongside the manifest block. Phase 2 pages get a richer system prompt that references architecture and implementation.

**25. Update `reviewer_node`** — when `state["research"]` is present, include the relevant `ToolImplementationNote` in the Reviewer's context. Extend checklist: no claims contradict Researcher's implementation notes.

**26. `--from-stage` caching** — implement in `cli.py`:
- `--from-stage write`: skip discovery and research; load `manifest.json` and `research.json` from disk; start graph at `planner_node`
- `--from-stage render`: skip everything; load approved pages from `output/pages/`; start at `render_node`
- This is critical for iterating on prompts without burning API credits

**Done criteria for Day 3:**
```bash
python3 -m cortexdocs generate \
  --server-cmd "npx tsx src/server/mcp-stdio.ts" \
  --server-cmd-cwd ~/Documents/dev/ai/ai-local-test \
  --repo ~/Documents/dev/ai/ai-local-test
# → output/research.json
# → output/pages/ includes architecture.md, setup.md, extending.md
# → output/llms-full.txt  (all pages concatenated)
# → output/site/          (re-rendered with new pages)
```

Spot-check: open `architecture.md` — does it accurately describe Cortex's Express + Supabase + Ollama stack? Open a tool page — is the implementation note correct?

Deploy updated site. Commit and tag: `git tag v0.2-phase2`.

---

## Day 4 — Eval harness + polish + demo prep

**Goal:** Running `make eval` produces `output/eval_report.md`. README is complete. Demo runs cleanly in 5–7 minutes.

### Morning: Eval harness

**27. `cortexdocs/eval/questions.py`** — the 15 reference questions (written on Day 0/1, not today). Three tiers:

*Tier 1 — answerable from manifest alone (api.json):*
- "What parameters does `capture_thought` take?"
- "Which tools accept a `limit` parameter?"
- "What is the difference between `search_thoughts` and `search_all`?"
- "Does the server expose any MCP resources or prompts?"
- "What types can a wiki page have?"

*Tier 2 — need Phase 1 docs (llms-full.txt, protocol only):*
- "When should I use `search_wiki` vs `list_wiki_pages`?"
- "What is the recommended order of calls to create a new wiki page?"
- "What does `wiki_health` check for, and what can it auto-fix?"
- "How do I do a dry run before running `batch_migrate_vault`?"
- "What happens if the librarian agent exceeds `max_iterations`?"

*Tier 3 — need Phase 2 docs (repo-enriched):*
- "What database does Cortex use to store thoughts, and what does the schema look like?"
- "How does Cortex generate embeddings, and what model does it use?"
- "When should I use `ingest_to_wiki` vs `write_wiki_page`?"
- "What is the librarian agent and how does it work internally?"
- "How does the stdio transport differ from the HTTP transport in this server?"

**28. `cortexdocs/eval/harness.py`** — `run_eval(questions, output_dir, config)`:
```python
for q in questions:
    answer_a = ask_llm(q.question, context=load_api_json())        # manifest only
    answer_b = ask_llm(q.question, context=load_llms_full_txt())   # Phase 1 docs
    answer_c = ask_llm(q.question, context=load_llms_full_txt())   # Phase 1+2 docs
    # (b and c are the same file — diff shows when Phase 2 pages are present)
    scores = judge(q, answer_a, answer_b, answer_c)
    log_result(q, answer_a, answer_b, answer_c, scores)
```

Use `claude-sonnet-4-6` for answering (to keep costs down), `claude-opus-4-7` for the judge.

**29. `cortexdocs/eval/judge.py`** — single Opus call per question with all three answers presented simultaneously (labelled A, B, C — no context labels visible to the judge). Returns `{score_a, score_b, score_c, rationale}` as structured output.

**30. `cortexdocs/eval/report.py`** — generates `output/eval_report.md`:
- Summary table: per-question scores across three variants
- Aggregate stats: mean score by tier, mean score by variant
- Narrative: 2–3 paragraphs on what the data shows
- Sample: include one full Q/A/score block as a worked example

### Afternoon: Polish + demo prep

**31. `README.md`** — complete rewrite covering:
- What this project is (one paragraph)
- Quick start: `git clone → uv sync → cp .env.example .env → make generate` → live in 5 min
- What it produces (with screenshots or output excerpts)
- Architecture overview (one diagram, link to ARCHITECTURE.md for detail)
- Eval results summary (link to eval_report.md)
- What I learned (3–5 bullet points — honest, specific, no boilerplate)
- Limitations section

**32. Final checks:**
- [ ] `uv sync` from scratch in a clean directory — does it install cleanly?
- [ ] `make generate` runs end-to-end without manual intervention
- [ ] `make serve` starts the docs site
- [ ] `make eval` produces the report
- [ ] `make deploy` pushes to GitHub Pages
- [ ] All `output/` and `logs/` gitignored; no secrets in repo

**33. Demo run-through** (timed, 5–7 minutes):
1. Show the README (30 sec)
2. Run `make generate --phase1-only` live or play the recording (1 min) — emphasize "any MCP server"
3. Show the generated docs site — click through one tool page (1 min)
4. Show `api.json` and `llms.txt` — explain the machine-first design (1 min)
5. Run `make generate` (full, with repo) or show the diff between Phase 1 and Phase 2 pages (1 min)
6. Show the eval report — highlight where repo knowledge changes the score (1 min)
7. "How would you apply this to Salesforce?" — you lead this (open-ended)

**Record a backup video** of steps 2–6 on Day 4 morning. If anything breaks live, play the video.

---

## Build order dependencies

The dependency chain below shows what must exist before each file can be tested:

```
pyproject.toml + uv sync
  └── config.py
        └── cli.py (skeleton)
              └── discovery/models.py
                    └── discovery/mcp_client.py
                          └── [Day 1 done — manifest.json on disk]
                                └── logging_util.py
                                      └── agents/state.py
                                            └── agents/graph.py (skeleton)
                                                  └── agents/planner.py
                                                        └── agents/writer.py
                                                              └── agents/reviewer.py
                                                                    └── render/machine_artifacts.py
                                                                          └── render/human_site.py
                                                                                └── [Day 2 done — site live]
                                                                                      └── ingest/models.py
                                                                                            └── ingest/walker.py
                                                                                                  └── agents/researcher.py
                                                                                                        └── [Day 3 done]
                                                                                                              └── eval/*
                                                                                                                    └── [Day 4 done]
```

---

## Prompt design notes

These decisions should be locked in before Day 2 begins to avoid rewriting prompts mid-build.

**Planner system prompt** — give it the manifest as JSON and ask for a `DocPlan` with explicit instructions on page types. Emphasize: one page per tool, named `tools/<tool-name>.md`; overview at `index.md`; tools index at `tools/index.md`. Output as JSON matching `DocPlan` schema.

**Writer system prompt** — three parts: (1) your role as a technical writer producing docs for both human developers and AI agents; (2) the frontmatter schema it must produce on every page; (3) the audience guidelines — human pages use prose and examples, machine pages use dense structured descriptions with no padding. The manifest JSON is in the user message as a cached block, not the system prompt (system prompts are harder to cache selectively).

**Reviewer system prompt** — give it a numbered checklist, not free-form instructions. Structured checklists produce more consistent outputs than prose instructions. Output must be `{"status": "approved"|"revise", "notes": "..."}` — use tool use or constrained output to enforce this. Do not let the Reviewer write long essays; cap `notes` at 200 words.

**Researcher system prompt** — instruct it to produce `ResearchOutput` JSON only (no prose preamble). Explicitly tell it: "Your output will be cached and reused by the Writer for all subsequent pages. Be thorough on `tool_notes` — the Writer cannot see the source files."

---

## Cost estimates (rough)

| Stage | Model | Est. input tokens | Est. output tokens | Est. cost |
|---|---|---|---|---|
| Discovery | — | — | — | $0 |
| Researcher | Opus | ~80k (repo) | ~4k | ~$2.00 |
| Planner | Sonnet | ~5k | ~2k | ~$0.05 |
| Writer × 20 pages | Sonnet | ~8k/page (cached) | ~1k/page | ~$0.80 |
| Reviewer × 20 pages | Opus | ~6k/page (cached) | ~0.5k/page | ~$1.20 |
| Eval harness | Sonnet + Opus | ~30k total | ~5k total | ~$0.50 |
| **Total** | | | | **~$4.55** |

Cache hits on the manifest + research blocks should cut Writer and Reviewer costs by ~70% after the first page. Actual costs will vary; monitor via logs.

---

## Risks and mitigations (implementation-specific)

| Risk | When it bites | Mitigation |
|---|---|---|
| `mcp` Python SDK version mismatch with Cortex's SDK | Day 1 | Check Cortex's `package.json` for `@modelcontextprotocol/sdk` version; ensure the Python client's protocol version is compatible. MCP is versioned; `tools/list` has been stable since 0.9. |
| Cortex stdio process hangs on startup | Day 1 | Add a 10s timeout to the `ClientSession.initialize()` call. Print stderr from the subprocess to diagnose. |
| LangGraph `Send` API behaves differently than expected for the writer loop | Day 2 | Fall back to managing `current_page_index` in state manually — it's 10 lines of logic and fully predictable. Don't spend more than 30 minutes on LangGraph-specific patterns. |
| Writer produces invalid frontmatter (YAML parse fails) | Day 2 | Wrap page parsing in a try/except; if frontmatter is malformed, pass the raw error text back as `reviewer_notes` for a free revision round. |
| Researcher hallucinates architecture details | Day 3 | The Reviewer's checklist catches contradictions with the manifest. For architecture claims not checkable by the Reviewer, spot-check two pages manually on Day 3 evening. |
| Eval results show no meaningful difference between variants | Day 4 | This is a valid finding — write it up honestly. The Tier 3 questions (implementation-level) should show a clear difference; if they don't, investigate whether Phase 2 pages are being included in `llms-full.txt`. |

---

## Fallback plan

If Day 3 slips significantly, ship with Phase 1 only:
- The tool reference pages + `api.json` + `llms.txt` are a complete deliverable.
- Write a `WHAT_WOULD_COME_NEXT.md` section in the README describing Phase 2.
- The eval still runs, just without Tier 3 questions.

The interview demo works equally well at Day 2 completion. Phase 2 makes it better, not necessary.
