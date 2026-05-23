# CortexDocs

An AI-powered documentation generator for MCP (Model Context Protocol) servers. It connects to a live MCP server, discovers its tool catalog, and runs a multi-agent pipeline to produce documentation for two audiences simultaneously: human developers reading rendered web pages, and AI agents consuming machine-optimized variants of the same content.

Built as a demonstration of multi-agent document generation using LangGraph and the Anthropic API.

## What it produces

Running `cortexdocs generate` against the Cortex MCP server outputs:

| Artifact | Path | Purpose |
|---|---|---|
| MkDocs site | `output/site/` | Human-readable docs, rendered with Material theme |
| `api.json` | `output/api.json` | Machine-readable tool reference (names, schemas, doc links) |
| `llms.txt` | `output/llms.txt` | Table of contents following [llmstxt.org](https://llmstxt.org/) convention |
| `llms-full.txt` | `output/llms-full.txt` | All pages concatenated, frontmatter stripped — drop into any LLM context |
| `manifest.json` | `output/manifest.json` | Raw `tools/list` response from the server |

For the Cortex server (12 tools), this produces 14 documentation pages covering the overview, a tools index, and one reference page per tool.

## How it works

```
MCP server (stdio or HTTP)
    │
    ▼ tools/list, resources/list, prompts/list
[Discovery]  →  manifest.json           (no LLM)
    │
    ▼
[Planner]    →  doc plan (page list)    Sonnet
    │
    ▼
[Writer]     →  markdown pages          Sonnet
    │  ▲ revision notes
    ▼  │
[Reviewer]   →  approve / revise        Opus  (max 2 revision rounds per page)
    │
    ▼
[Render]     →  site/ + machine artifacts   (no LLM)
```

**Protocol-first:** tool definitions come from `tools/list`, not from parsing source code. This means the pipeline works against any MCP server without knowing its implementation language or structure.

**Bounded review loop:** the Reviewer runs a checklist against the manifest — catching hallucinated parameter names, wrong types, and invented return schemas. It sends revision notes back to the Writer for up to two rounds, then ships whatever it has.

**Prompt caching:** the manifest JSON is cached across all Writer and Reviewer calls, keeping per-page API costs low after the first call.

## Setup

**Prerequisites:** Python 3.11+, `uv`, an Anthropic API key, and Node.js (to run the Cortex MCP server via `npx`).

```bash
# 1. Clone and install dependencies
git clone https://github.com/rdixon22/mcp-doc-gen.git
cd mcp-doc-gen
uv sync

# 2. Configure
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY and SERVER_CMD_CWD
```

**.env.example:**
```
ANTHROPIC_API_KEY=sk-ant-...

SERVER_CMD=npx tsx src/server/mcp-stdio.ts
SERVER_CMD_CWD=/path/to/cortex-repo
SERVER_ENV_FILE=/path/to/cortex-repo/.env

# Optional: set this to enable Phase 2 repo enrichment (once implemented)
# REPO_PATH=/path/to/cortex-repo
```

## Running

```bash
# Generate docs (Phase 1: protocol-only, no repo required)
REPO_PATH= uv run python3 -m cortexdocs generate --no-eval

# View the generated site locally
uv run python3 -m cortexdocs serve

# Deploy to GitHub Pages
uv run mkdocs gh-deploy --config-file output/mkdocs.yml

# Re-run from the write stage (skip re-discovery, use cached manifest.json)
REPO_PATH= uv run python3 -m cortexdocs generate --no-eval --from-stage write

# Re-render only (use existing pages, skip all LLM calls)
REPO_PATH= uv run python3 -m cortexdocs generate --no-eval --from-stage render
```

The `REPO_PATH=` prefix overrides the env file setting for Phase 1-only runs. If your `.env` does not set `REPO_PATH`, you can omit it.

## Project status

| Feature | Status |
|---|---|
| MCP discovery (any server) | Done |
| Planner → Writer → Reviewer pipeline | Done |
| MkDocs site rendering | Done |
| Machine artifacts (api.json, llms.txt) | Done |
| GitHub Pages deploy | Done |
| Phase 2: repo enrichment (architecture, setup, extension guides) | Planned |
| Evaluation harness | Planned |

## Architecture

See [plans/ARCHITECTURE.md](plans/ARCHITECTURE.md) for the full design, data models, and LangGraph graph topology.

See [CLAUDE.md](CLAUDE.md) for AI-agent-oriented documentation: file layout, known quirks, implementation status, and running the project.

## Tech stack

Python · LangGraph · Anthropic API (Sonnet + Opus) · MCP Python SDK · MkDocs Material · pydantic-settings · typer

## What was learned

- **Protocol-first beats code-first for tool discovery.** `tools/list` gives you clean JSON Schema directly; static analysis of TypeScript/Zod gives you parsing headaches and edge cases.
- **The Reviewer earns its token cost.** Without it, the Writer consistently invents plausible-but-wrong return value schemas. The review loop catches this reliably, especially on tools whose descriptions don't specify return types.
- **Prompt caching is essential at scale.** For 14 pages × 3 potential calls each, caching the manifest JSON block reduces costs by roughly 70% after the first page.
- **`--from-stage` iteration is non-negotiable.** Being able to re-run just the write or render stage without re-discovering the server cuts iteration time from minutes to seconds during prompt tuning.
