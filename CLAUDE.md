# CortexDocs — AI Agent Guide

## What this project is

A multi-agent documentation generator for MCP (Model Context Protocol) servers. It connects to a live MCP server, discovers its tool manifest, and runs a Planner → Writer → Reviewer pipeline to produce:
- A rendered MkDocs Material site for human developers
- Machine-optimized artifacts (`llms.txt`, `llms-full.txt`, `api.json`) for AI agents

The primary target is the Cortex MCP server (`ai-local-test` repo), but the pipeline works against **any** MCP server without modification.

## Tech stack

| Concern | Choice |
|---|---|
| Language | Python 3.11+ (tested on 3.13) |
| Dependency management | `uv` |
| LLM | Anthropic API — `claude-sonnet-4-6` (planner, writer), `claude-opus-4-7` (reviewer) |
| Agent framework | LangGraph (`StateGraph` + SQLite checkpointing) |
| MCP client | `mcp` Python SDK |
| Config | `pydantic-settings` (reads `.env`) |
| Site rendering | MkDocs Material |
| CLI | `typer` + `rich` |

## Repository layout

```
cortexdocs/
├── cli.py                  # Entry point. typer app: generate / serve / eval-docs
├── config.py               # Settings (pydantic-settings, reads .env)
├── logging_util.py         # agent_log() context manager — writes logs/<ts>_<agent>.json
├── discovery/
│   ├── mcp_client.py       # Connects to MCP server; calls tools/list, resources/list, prompts/list
│   └── models.py           # MCPServerManifest, MCPToolDef, MCPToolParam (Pydantic)
├── ingest/
│   └── walker.py           # STUB (Phase 2) — will walk repo, classify files
├── agents/
│   ├── state.py            # PipelineState TypedDict + DocPageSpec / DocPlan / DocPage models
│   ├── graph.py            # StateGraph wiring — routes planner → writer → reviewer → render
│   ├── planner.py          # Sonnet: manifest → DocPlan (ordered page list)
│   ├── writer.py           # Sonnet: DocPageSpec → full markdown page (+ revision handling)
│   ├── reviewer.py         # Opus: approves page or returns revision notes (max 2 rounds)
│   └── researcher.py       # STUB (Phase 2) — will produce ResearchOutput from repo
└── render/
    ├── human_site.py       # render_node: writes MkDocs site_src/, runs mkdocs build
    └── machine_artifacts.py # write_api_json / write_llms_txt / write_llms_full_txt

output/                     # Generated artifacts (gitignored)
├── manifest.json           # Raw tools/list response
├── pages/                  # Raw markdown from Writer
├── site/                   # Rendered HTML from MkDocs
├── site_src/               # MkDocs source (docs/ directory)
├── mkdocs.yml              # Generated MkDocs config (absolute paths)
├── api.json                # Machine-readable tool reference
├── llms.txt                # llmstxt.org TOC
├── llms-full.txt           # All pages concatenated, frontmatter stripped
└── checkpoints.db          # LangGraph SQLite checkpoint store

logs/                       # One JSON file per agent call (gitignored)
plans/                      # BRIEF.md, ARCHITECTURE.md, IMPLEMENTATION.md
```

## Pipeline stages

```
[discover]  mcp_client.py — no LLM, pure SDK call → manifest.json
    │
    ├─ if REPO_PATH set ──► [ingest] walker.py (STUB) → [researcher] (STUB)
    │
    ▼
[planner]   Sonnet — manifest → DocPlan (14 pages for Cortex)
    ▼
[writer]    Sonnet — one call per page; revision calls if reviewer returns notes
    ▼
[reviewer]  Opus — checklist review; max 2 revision rounds then ships "partial"
    ▼
[render]    pure Python — machine artifacts + mkdocs build
```

## Implementation status

| Stage | Status |
|---|---|
| Phase 1: Discovery | Complete |
| Phase 1: Planner → Writer → Reviewer | Complete |
| Phase 1: Render (site + machine artifacts) | Complete |
| Phase 1: Deploy (mkdocs gh-deploy) | Complete |
| Phase 2: Ingest (walker.py) | **Stub** |
| Phase 2: Researcher agent | **Stub** |
| Eval harness | **Stub** (Day 4) |

## Key design decisions

**Protocol-first.** `tools/list` is the authoritative source for tool definitions. No static code analysis or regex parsing of Zod chains. The manifest is what the server actually exposes at runtime.

**Prompt caching.** The manifest JSON is wrapped with `cache_control: {"type": "ephemeral"}` in every Writer and Reviewer call. For 14 pages × up to 3 calls each, this drives cache hit rate to ~95% after the first page.

**Bounded review loop.** `reviewer_node` tracks `revision_counts[page_id]`. At 2 revisions it forces `review_status = "partial"` and advances. Prevents oscillation.

**Phase separation.** Phase 1 works on any MCP server with no source access. Phase 2 (when implemented) adds repo context via the Researcher. The graph wires Phase 2 nodes only when `settings.repo_path` is set.

**`--from-stage` for iteration.** The CLI's `--from-stage write` reloads `manifest.json` from disk and skips re-discovery. `--from-stage render` skips everything and just re-renders. Critical for iterating on prompts without burning API credits.

## Running the project

```bash
# Install deps (first time, or after pulling)
uv sync

# Phase 1 only (no repo enrichment)
REPO_PATH= uv run python3 -m cortexdocs generate --no-eval

# Phase 1 + Phase 2 (when Phase 2 is implemented)
uv run python3 -m cortexdocs generate

# Re-run from write stage (cached manifest, skips discovery)
REPO_PATH= uv run python3 -m cortexdocs generate --no-eval --from-stage write

# Re-render only (use existing pages)
REPO_PATH= uv run python3 -m cortexdocs generate --no-eval --from-stage render

# Serve locally
uv run python3 -m cortexdocs serve

# Deploy to GitHub Pages
uv run mkdocs gh-deploy --config-file output/mkdocs.yml
```

`REPO_PATH=` (empty env override) is required when you want Phase 1 only but `.env` has `REPO_PATH` set.

## Configuration (.env)

```
ANTHROPIC_API_KEY=sk-ant-...

# Phase 1 — MCP server connection
SERVER_CMD=npx tsx src/server/mcp-stdio.ts
SERVER_CMD_CWD=/path/to/cortex-repo
SERVER_ENV_FILE=/path/to/cortex-repo/.env   # optional: load server's own .env

# Phase 2 — repo enrichment (omit or leave empty for Phase 1 only)
REPO_PATH=/path/to/cortex-repo
```

## Known quirks

- The Cortex server prints `"Ollama host: ..."` to stdout on startup, which causes a harmless JSONRPC parse warning. The MCP SDK recovers; discovery completes normally.
- `uv run` is required (not bare `python3`) because there is a conflicting system Python environment with a `VIRTUAL_ENV` variable.
- Writer reliably hallucinates return value JSON schema (field names not in the manifest). The Reviewer catches these. This is expected and is why the review loop exists.
- `mkdocs gh-deploy` requires GitHub Pages to be enabled in repo settings (Settings → Pages → Source: `gh-pages` branch) after the first push.
- The generated `output/mkdocs.yml` uses absolute paths — it is not portable across machines and should not be committed.

## What is NOT implemented yet

- `cortexdocs/ingest/walker.py` — `ingest_node` raises `NotImplementedError("ingest_node — Day 3")`
- `cortexdocs/agents/researcher.py` — `researcher_node` raises `NotImplementedError("researcher_node — Day 3")`
- `cortexdocs/eval/` — eval harness skeleton only; `eval-docs` command prints a stub message
- `cortexdocs/ingest/models.py` — `SourceFile` / `IngestedRepo` models not yet written
