# CortexDocs — Architecture

**Status:** Draft v0.2
**Date:** 2026-05-21
**Based on:** [BRIEF.md](BRIEF.md)

---

## Language & Framework Decision

The brief listed TypeScript as the language and left the agent framework as a pending decision (leaning LangGraph). This architecture resolves both:

**Python + LangGraph (Python SDK).**

Reasons:
- LangGraph's Python SDK is more mature and better documented than the JS equivalent.
- Anthropic's Python SDK (`anthropic`) is the reference client; all examples, prompt caching docs, and tool-use patterns are Python-first.
- Python's data ecosystem (Pydantic) makes structured JSON outputs between agents clean to validate.
- MkDocs Material is a Python-native tool — the render step lives in the same runtime with no subprocess boundary.
- The `mcp` Python SDK can connect to any MCP server directly, which drives the pipeline strategy below.
- The tradeoff: you lose "same language as Cortex." The mitigation is that the pipeline never modifies Cortex — it reads it. The language boundary is fine.

The entry point is `python -m cortexdocs generate` (or `make generate`), mirroring the brief's `pnpm run generate` intent.

---

## Pipeline Strategy: Protocol-First, Repo-Enriched

The pipeline runs in two phases. Phase 1 is always required. Phase 2 is optional but produces substantially richer documentation.

### Phase 1 — Protocol Discovery (always runs)

Connect to the live MCP server using the MCP Python SDK and call `tools/list` (plus `resources/list` and `prompts/list` if the server supports them). This returns the server's canonical tool manifest: names, descriptions, and full JSON Schema for every input parameter.

This is the authoritative source for tool definitions — more reliable than static code analysis because it reflects what the server actually exposes at runtime, regardless of implementation language or registration pattern. It also means the pipeline works against **any MCP server** without knowing anything about its codebase.

Phase 1 alone produces a complete baseline documentation set:
- A per-tool reference page for every tool in the manifest
- A tools index page
- `api.json` and `llms.txt` machine artifacts

### Phase 2 — Repo Enrichment (optional, triggered by `--repo`)

If a repo path is provided, the pipeline walks the source tree, classifies files, and passes both the manifest (from Phase 1) and the repo content to the Researcher agent. The Researcher can now produce architecture, setup, and extension-point documentation that would be impossible from the protocol alone.

Phase 2 enriches the baseline pages and adds new ones:
- Architecture overview
- Setup guide
- Developer extension guide
- Deeper per-tool pages with implementation notes

The Reviewer in Phase 2 has two truth sources: the manifest (protocol ground truth) and the Researcher's repo analysis.

### Why this ordering matters

Tools/list gives you clean JSON Schema directly from the MCP SDK — no regex parsing of Zod chains, no language-specific extraction heuristics. The manifest is the most reliable thing we can know about the server. Everything the repo adds is commentary on top of it.

---

## Repository Layout

```
mcp-doc-gen/
├── cortexdocs/                     # main Python package
│   ├── __init__.py
│   ├── cli.py                      # entry point: `python -m cortexdocs`
│   ├── config.py                   # Settings (pydantic-settings, reads .env)
│   │
│   ├── discovery/                  # Phase 1 — live server connection
│   │   ├── __init__.py
│   │   ├── mcp_client.py           # connects to server, calls tools/list etc.
│   │   └── models.py               # MCPServerManifest, MCPToolDef (Pydantic)
│   │
│   ├── ingest/                     # Phase 2 — repo analysis (optional)
│   │   ├── __init__.py
│   │   ├── walker.py               # recursive file walk + classifier
│   │   └── models.py               # IngestedRepo, SourceFile (Pydantic)
│   │
│   ├── agents/                     # LangGraph pipeline
│   │   ├── __init__.py
│   │   ├── graph.py                # StateGraph definition — the wiring
│   │   ├── state.py                # PipelineState TypedDict
│   │   ├── researcher.py           # Researcher node (Phase 2 only)
│   │   ├── writer.py               # Writer node (plan + per-page loop)
│   │   └── reviewer.py             # Reviewer node (bounded loop)
│   │
│   ├── render/                     # Output rendering
│   │   ├── __init__.py
│   │   ├── human_site.py           # writes MkDocs Material project + mkdocs.yml
│   │   └── machine_artifacts.py    # writes llms.txt, llms-full.txt, api.json
│   │
│   ├── eval/                       # Evaluation harness
│   │   ├── __init__.py
│   │   ├── harness.py              # runs questions against each context variant
│   │   ├── judge.py                # LLM-as-judge scorer
│   │   └── questions.py            # 10–15 reference Q&A pairs (hardcoded)
│   │
│   └── logging_util.py             # structured JSON log writer (all agent I/O)
│
├── output/                         # generated artifacts (gitignored)
│   ├── manifest.json               # raw tools/list output
│   ├── research.json               # Researcher output (Phase 2 only)
│   ├── doc_plan.json
│   ├── pages/                      # raw markdown from Writer
│   ├── site/                       # MkDocs rendered HTML
│   ├── llms.txt
│   ├── llms-full.txt
│   ├── api.json
│   └── eval_report.md
│
├── logs/                           # agent run logs (gitignored)
│   └── <timestamp>_<agent>.json
│
├── plans/
│   ├── BRIEF.md
│   └── ARCHITECTURE.md
│
├── tests/
│   └── ...
│
├── pyproject.toml                  # dependencies + scripts
├── Makefile                        # convenience targets
├── mkdocs.yml.tmpl                 # template for the human site config
├── .env.example
└── README.md
```

---

## Data Flow

```
MCP server (stdio cmd or HTTP URL)
        │
        ▼
┌────────────────────┐
│  Phase 1: Discover │  tools/list → resources/list → prompts/list
│  mcp_client.py     │
└─────────┬──────────┘
          │  MCPServerManifest  (saved to output/manifest.json)
          │
          ├─────────────── repo path provided? ──────────────────────┐
          │                                                           │
          ▼  NO                                              YES      ▼
    [planner_node]                                    ┌──────────────────────┐
    (manifest only)                                   │  Phase 2: Ingest     │
          │                                           │  walker.py           │
          │                                           └──────────┬───────────┘
          │                                                      │  IngestedRepo
          │                                                      ▼
          │                                           ┌──────────────────────┐
          │                                           │  [researcher_node]   │
          │                                           │  Opus — one shot     │
          │                                           └──────────┬───────────┘
          │                                                      │  ResearchOutput
          │                                                      │  (saved to output/research.json)
          └──────────────────────────────────────────────────────┤
                                                                 ▼
                                                        [planner_node]
                                                        (manifest + research)
                                                                 │
                                                                 ▼
                                                        [writer_node]   ◄──────────┐
                                                        Sonnet                      │ revision_notes
                                                                 │                  │
                                                                 ▼                  │
                                                        [reviewer_node]  ───────────┘
                                                        Opus  (≤2 rounds per page)
                                                                 │  approved pages
                                                                 ▼
                                              ┌─────────────────────────────┐
                                              │   Render                    │
                                              │  ├─ human_site.py           │ → output/site/
                                              │  └─ machine_artifacts.py    │ → llms.txt, api.json
                                              └──────────────┬──────────────┘
                                                             │
                                                             ▼
                                              ┌─────────────────────────────┐
                                              │   Eval  (optional)          │
                                              │  3 context variants × N Qs  │ → eval_report.md
                                              └─────────────────────────────┘
```

---

## LangGraph State Machine

### PipelineState

```python
class PipelineState(TypedDict):
    # Phase 1 inputs (always present)
    manifest: MCPServerManifest

    # Phase 2 inputs (None if no repo provided)
    ingested_repo: IngestedRepo | None
    research: ResearchOutput | None

    # writer / reviewer state
    doc_plan: DocPlan | None
    pages: list[DocPage]                  # grows as Writer produces pages
    current_page_index: int
    revision_counts: dict[str, int]       # page_id → revision count
    approved_pages: list[DocPage]

    # pipeline mode
    repo_enriched: bool                   # True when Phase 2 ran

    # control
    errors: list[str]
    token_usage: dict[str, int]           # cumulative per-agent
```

### Graph Topology

```
START
  │
  ▼
[discover_node]         pure Python — mcp_client.py, no LLM
  │
  ├── repo path set? ──► [ingest_node]       pure Python — walker.py
  │                           │
  │                           ▼
  │                      [researcher_node]   Anthropic Opus — one shot
  │                           │
  └───────────────────────────┤
                              ▼
                        [planner_node]       Anthropic Sonnet — produce DocPlan
                              │
                              ▼
                        [writer_node]        Anthropic Sonnet — one page per call
                              │   ▲
                              │   │ revision_notes
                              ▼   │
                        [reviewer_node]      Anthropic Opus — approve or return notes
                              │
                              ├── more pages? ──► [writer_node]
                              │
                              ▼
                        [render_node]        pure Python
                              │
                              ▼
                        [eval_node]          optional, flag-gated
                              │
                              ▼
                             END
```

**Edge conditions:**

- `discover_node → ingest_node`: if `config.repo_path` is set
- `discover_node → planner_node`: if no repo path (skip Phases 2 nodes entirely)
- `ingest_node → researcher_node`: always (only reached when repo is present)
- `researcher_node → planner_node`: always
- `writer_node → reviewer_node`: always
- `reviewer_node → writer_node`: if `status == "revise"` AND `revision_counts[page_id] < 2`
- `reviewer_node → writer_node (next page)`: if approved OR revision cap reached
- `reviewer_node → render_node`: when all pages are processed
- Pages that hit the revision cap are flagged with `reviewed: partial` in frontmatter.

---

## Key Data Models (Pydantic)

```python
# discovery/models.py

class MCPToolParam(BaseModel):
    name: str
    description: str | None
    type: str                     # JSON Schema type string
    required: bool
    schema: dict                  # full JSON Schema for this param

class MCPToolDef(BaseModel):
    name: str
    description: str
    params: list[MCPToolParam]
    raw_input_schema: dict        # verbatim inputSchema from tools/list

class MCPServerManifest(BaseModel):
    server_name: str
    server_version: str | None
    tools: list[MCPToolDef]
    resources: list[dict]         # raw resources/list response (may be empty)
    prompts: list[dict]           # raw prompts/list response (may be empty)
    transport: Literal["stdio", "http"]
    discovered_at: str            # ISO timestamp


# ingest/models.py  (Phase 2 only)

class SourceFile(BaseModel):
    path: str
    classification: Literal["mcp_registration", "handler", "config", "test", "util", "docs", "other"]
    size_bytes: int
    content: str | None           # None if file exceeds token budget

class IngestedRepo(BaseModel):
    root_path: str
    files: list[SourceFile]
    total_files: int
    skipped_files: list[str]


# agents/state.py

class ModuleSummary(BaseModel):
    path: str
    purpose: str
    key_exports: list[str]
    dependencies: list[str]

class ToolImplementationNote(BaseModel):
    tool_name: str                # matches MCPToolDef.name
    implementation_file: str
    how_it_works: str             # 2–4 sentence prose
    dependencies: list[str]       # external services, libs

class ResearchOutput(BaseModel):
    repo_name: str
    repo_purpose: str
    architecture_summary: str
    module_summaries: list[ModuleSummary]
    tool_notes: list[ToolImplementationNote]   # one per tool, keyed to manifest
    setup_steps: list[str]
    extension_points: list[str]

class DocPageSpec(BaseModel):
    page_id: str
    title: str
    filename: str
    audience: Literal["human", "both"]
    phase: Literal[1, 2]          # 1 = protocol-only page, 2 = requires repo research
    key_points: list[str]

class DocPlan(BaseModel):
    pages: list[DocPageSpec]

class DocPage(BaseModel):
    spec: DocPageSpec
    content: str                  # full markdown including frontmatter
    revision_count: int
    review_status: Literal["approved", "partial", "pending"]
    reviewer_notes: str | None
```

---

## Agent Design

### Discovery (no LLM)

`mcp_client.py` uses the `mcp` Python SDK to connect to the server and retrieve its manifest. Two transport modes:

- **stdio:** spawns the server process via `subprocess`, connects with `StdioClientTransport`. Config: `server_cmd = "npx tsx src/server/mcp-stdio.ts"`.
- **HTTP:** connects to a running server via `StreamableHTTPClientTransport`. Config: `server_url = "http://localhost:3000/mcp"`.

Output is `MCPServerManifest`, serialized to `output/manifest.json`. This is always the first step and cannot be skipped.

### Researcher (Phase 2 only)

- **Model:** `claude-opus-4-7`
- **Input:** `MCPServerManifest` (Phase 1 output, cached) + `IngestedRepo` serialized to JSON.
- **Output:** `ResearchOutput` — architecture summary, module summaries, per-tool implementation notes keyed to manifest tool names, setup steps, extension points.
- **Token strategy:** Files below 2000 tokens are sent inline. Larger files are summarized first with a separate Sonnet call, then the summary is sent. Total budget: 200k tokens.
- **Prompt caching:** The manifest block is marked `cache_control: {"type": "ephemeral"}` since it is identical across all agent calls. The repo content block is also cached — on iterative dev runs, this is the expensive block that should hit cache.
- **One shot** — no review loop on the Researcher.

### Planner

- **Model:** `claude-sonnet-4-6`
- **Input:** `MCPServerManifest` (always) + `ResearchOutput` (if Phase 2 ran, else `None`).
- **Output:** `DocPlan` — ordered list of `DocPageSpec`. Pages are tagged with `phase: 1` (derivable from manifest alone) or `phase: 2` (requires repo research). If no repo was provided, `phase: 2` pages are omitted.
- **One shot.**

### Writer

- **Model:** `claude-sonnet-4-6`
- **Input per call:** `MCPServerManifest` (cached) + `ResearchOutput | None` (cached if present) + `DocPageSpec` + optional `reviewer_notes`.
- **Output:** Full markdown page with YAML frontmatter block.
- **Frontmatter schema:**
  ```yaml
  ---
  title: "..."
  description: "..."
  audience: human | machine | both
  topics: [list of keywords]
  mcp_tools: [tool names referenced on this page]
  doc_phase: 1 | 2
  reviewed: approved | partial
  generated_at: ISO timestamp
  model: claude-sonnet-4-6
  ---
  ```
- Called once per page plus up to 2 revision calls if the Reviewer returns notes.

### Reviewer

- **Model:** `claude-opus-4-7`
- **Input per call:** The generated `DocPage.content` + the relevant tools from `MCPServerManifest` (ground truth for tool names, descriptions, schema) + the relevant `ToolImplementationNote` entries from `ResearchOutput` if available.
- **Output:** `{status: "approved" | "revise", notes: str | None}`.
- **Checklist in system prompt:**
  - Tool names and descriptions match the manifest exactly
  - Parameter names and types match the raw input schema
  - No claims about implementation that contradict the Researcher's notes
  - Audience alignment (human vs. machine pages have different standards)
  - Frontmatter is valid and complete
- **Hard cap:** if `revision_counts[page_id] >= 2`, flag and move on.

---

## Discovery: Connecting to the MCP Server

```python
# discovery/mcp_client.py  (simplified)

async def discover(config: Settings) -> MCPServerManifest:
    if config.server_cmd:
        transport = StdioClientTransport(command=config.server_cmd)
        transport_type = "stdio"
    else:
        transport = StreamableHTTPClientTransport(url=config.server_url)
        transport_type = "http"

    async with ClientSession(transport) as session:
        await session.initialize()
        tools_result   = await session.list_tools()
        resources_result = await session.list_resources()   # may be empty
        prompts_result   = await session.list_prompts()     # may be empty

        return MCPServerManifest(
            server_name=session.server_info.name,
            server_version=session.server_info.version,
            tools=[_parse_tool(t) for t in tools_result.tools],
            resources=[r.model_dump() for r in resources_result.resources],
            prompts=[p.model_dump() for p in prompts_result.prompts],
            transport=transport_type,
            discovered_at=datetime.utcnow().isoformat(),
        )
```

For Cortex specifically: the stdio transport spawns `npx tsx src/server/mcp-stdio.ts` from the repo root. The HTTP transport connects to the Express server at `http://localhost:3000/mcp` with the `x-cortex-key` header if `MCP_ACCESS_KEY` is configured.

---

## Ingestion Pipeline (Phase 2)

```
walker.py
  ├── os.walk the repo root
  ├── skip: .git, node_modules, __pycache__, dist, build, *.lock, binaries
  ├── classify each .ts / .js / .json / .md file
  └── enforce token budget (default: 200k tokens total)
```

File classification logic (in order):
1. Contains `server.registerTool(` → `mcp_registration`
2. Contains `setRequestHandler` or `router.` → `handler`
3. Name matches `*config*`, `*settings*` → `config`
4. Name matches `*.test.*`, `*.spec.*` → `test`
5. Extension `.md` → `docs`
6. Otherwise → `util`

No tree-sitter, no AST parsing. Tool definitions come from the manifest (Phase 1), not from static extraction. The repo walk is purely for providing context to the Researcher about architecture, setup, and implementation — the Researcher sends large source files to Claude for comprehension, not to an extractor.

---

## Machine Artifacts

### `api.json`
Generated from `MCPServerManifest` — this is a direct serialization of what the server reported via `tools/list`. No LLM involved, no risk of hallucination.

```json
{
  "schema_version": "1.0",
  "generated_at": "...",
  "server_name": "cortex",
  "server_version": "2.0.0",
  "transport": "stdio",
  "mcp_tools": [
    {
      "name": "capture_thought",
      "description": "...",
      "input_schema": { ... },
      "doc_page": "tools/capture-thought.md"
    }
  ],
  "resources": [],
  "prompts": []
}
```

### `llms.txt`
Single-file table of contents following the [llms.txt convention](https://llmstxt.org/):
```
# Cortex MCP Server

> [one-line description from manifest or ResearchOutput]

## MCP Tools
- [capture-thought](llms/tools/capture-thought.md): Save a new note or thought to Cortex
...

## Pages
- [Overview](llms/overview.md)
- [Architecture](llms/architecture.md)   ← Phase 2 only
...
```

### `llms-full.txt`
All approved pages concatenated with `---` separators, frontmatter stripped or flattened.

---

## Eval Harness

With two pipeline phases, the eval can compare three context variants:

```
eval/questions.py    — 10–15 Q&A pairs, written before the pipeline runs
                        each: {question, reference_answer, relevant_tools: [...]}

eval/harness.py
  for each question:
    ├── ask LLM with context_a = api.json only (pure manifest)       → answer_a
    ├── ask LLM with context_b = llms-full.txt (Phase 1 docs)        → answer_b
    └── ask LLM with context_c = llms-full.txt (Phase 1+2 docs)      → answer_c
        (context_b and context_c are the same file if only Phase 1 ran)

eval/judge.py
  for each question:
    ├── single Opus call scoring all three answers simultaneously
    ├── score 1–5 on accuracy + completeness against reference_answer
    └── return {score_a, score_b, score_c, rationale}

output:
  eval_report.md — per-question score table + narrative
                   key finding: what does repo knowledge add beyond the protocol?
```

The judge evaluates all three answers in a single call to control for ordering bias. The key question the report answers: **for which question types does repo enrichment actually improve answers?**

---

## Logging

Every agent call writes a JSON log entry to `logs/<ISO_timestamp>_<agent_name>.json`:

```json
{
  "agent": "writer",
  "model": "claude-sonnet-4-6",
  "timestamp": "2026-05-21T10:00:00Z",
  "input_tokens": 12450,
  "output_tokens": 980,
  "cache_read_tokens": 11200,
  "cache_write_tokens": 0,
  "input_summary": "page_id: capture-thought, phase: 1, revision: 0",
  "output_preview": "---\ntitle: capture_thought\n...",
  "full_input": "...",
  "full_output": "..."
}
```

`logging_util.py` is a thin context-manager wrapper — every agent node calls it. Logs are a demo asset: a reviewer can inspect exactly what the pipeline did, token by token.

---

## Configuration

`cortexdocs/config.py` via `pydantic-settings` (reads `.env`):

```python
class Settings(BaseSettings):
    anthropic_api_key: str

    # Phase 1 — one of these is required
    server_cmd: str | None = None       # e.g. "npx tsx src/server/mcp-stdio.ts"
    server_url: str | None = None       # e.g. "http://localhost:3000/mcp"
    server_cmd_cwd: str | None = None   # working dir for stdio process
    mcp_access_key: str | None = None   # passed as x-cortex-key header (HTTP only)

    # Phase 2 — optional
    repo_path: str | None = None        # if set, repo enrichment runs

    # Models
    researcher_model: str = "claude-opus-4-7"
    writer_model: str = "claude-sonnet-4-6"
    reviewer_model: str = "claude-opus-4-7"
    judge_model: str = "claude-opus-4-7"

    # Pipeline limits
    max_revision_rounds: int = 2
    file_token_budget: int = 200_000
    file_inline_threshold_tokens: int = 2_000

    # Output
    run_eval: bool = True
    log_dir: Path = Path("logs")
    output_dir: Path = Path("output")
```

---

## CLI Entry Points

```
# Minimal — protocol only, any MCP server
python -m cortexdocs generate --server-cmd "npx tsx src/server/mcp-stdio.ts" --server-cmd-cwd ~/path/to/repo

# Protocol + repo enrichment (Cortex full run)
python -m cortexdocs generate \
  --server-cmd "npx tsx src/server/mcp-stdio.ts" \
  --server-cmd-cwd ~/Documents/dev/ai/ai-local-test \
  --repo ~/Documents/dev/ai/ai-local-test

# HTTP transport variant
python -m cortexdocs generate \
  --server-url http://localhost:3000/mcp \
  --repo ~/Documents/dev/ai/ai-local-test

# Stage-level reruns (reads cached output from previous run)
python -m cortexdocs generate --from-stage write    # skip discover + ingest + research
python -m cortexdocs generate --from-stage render   # skip everything except render + eval

# Other commands
python -m cortexdocs eval      # rerun eval against existing output/pages/
python -m cortexdocs serve     # mkdocs serve output/site/
```

Implemented with `typer`.

---

## Key Dependencies

| Package | Purpose |
|---|---|
| `anthropic` | Anthropic Python SDK (models, streaming, prompt caching) |
| `mcp` | MCP Python SDK — client for `tools/list`, `resources/list`, stdio + HTTP transports |
| `langgraph` | Agent pipeline state machine + SQLite checkpointing |
| `pydantic` + `pydantic-settings` | Data models + config |
| `typer` | CLI |
| `mkdocs-material` | Human site rendering |
| `tiktoken` | Token counting for file budget enforcement |
| `rich` | Terminal progress output |

No vector store, no RAG, no embedding model.

---

## Prompt Caching Strategy

Caching is load-bearing for cost at the Writer/Reviewer loop scale:

1. **All agents:** `MCPServerManifest` JSON is marked `cache_control: {"type": "ephemeral"}`. It is identical across every Writer and Reviewer call. For 16 tools × up to 3 revision calls, this is 48 cache hits on the same block.
2. **Researcher:** The repo content block is also marked `ephemeral`. Re-runs during development (very common on day 2) hit cache. Expected cache hit rate: ~95% after first run.
3. **Writer / Reviewer:** `ResearchOutput` JSON (if present) is a second cached block. Every page call reuses it.

This makes the per-page write/review loop much cheaper than it looks: after the first page, the manifest and research context are both served from cache on every subsequent call.

---

## Open Questions (to resolve at kickoff)

1. **Server startup in the demo.** The Phase 1 step requires a running or startable MCP server. For the stdio transport, `mcp_client.py` spawns the process itself — no manual startup needed if `server_cmd` and `server_cmd_cwd` are set. Verify this works cleanly for Cortex (requires `node_modules` to be installed in the Cortex repo).

2. **Eval question set.** Write the 10–15 questions before running the pipeline, not after. Questions should span all three answer levels: some answerable from the manifest alone (tool names, parameter types), some requiring Phase 1 docs (usage patterns, when to use which tool), and some requiring Phase 2 (how to add a new tool, what Supabase schema is needed).

3. **`--from-stage` caching.** For iterative dev, the pipeline should detect when `output/manifest.json` already exists and skip re-discovery unless `--force` is passed. Similarly for `research.json`. This avoids burning API credits on repeated runs while debugging the Writer.

4. **MkDocs deployment.** GitHub Pages via `mkdocs gh-deploy` is one command. Include in the Makefile as `make deploy`. No CI needed.

5. **LangGraph checkpointing.** Enable SQLite checkpointing from day 1. If the pipeline crashes mid-Writer-loop, it resumes from the last approved page rather than starting over.

6. **Resources and prompts.** If the server exposes `resources/list` or `prompts/list`, generate reference pages for those too (same Writer/Reviewer loop, same frontmatter pattern). For Cortex these are likely empty, but the pipeline should handle them generically.
