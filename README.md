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
| `research.json` | `output/research.json` | Structured findings from the Researcher (Phase 2 runs only) |
| `eval_report.md` | `output/eval_report.md` | Blind 3-way scoring of the generated docs (see [Evaluation](#evaluation)) |

For the Cortex server (16 tools), a Phase 1 run produces 18 pages — an overview, a tools index, and one reference page per tool. A Phase 2 run adds architecture, setup, and extension guides, for 21 pages.

## How it works

```
MCP server (stdio or HTTP)
    │
    ▼ tools/list, resources/list, prompts/list
[Discovery]  →  manifest.json           (no LLM)
    │
    ├─ if REPO_PATH is set (Phase 2):
    │  [Ingest]     →  classified source files   (no LLM)
    │       ▼
    │  [Researcher] →  research.json             Opus
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

Evaluation runs separately, against the output of a completed run:

```
output/ artifacts
    │
    ▼
[Eval]       →  eval_report.md          Opus judge   (cortexdocs eval-docs)
```

**Protocol-first:** tool definitions come from `tools/list`, not from parsing source code. This means the pipeline works against any MCP server without knowing its implementation language or structure.

**Bounded review loop:** the Reviewer runs a checklist against the manifest — catching hallucinated parameter names, wrong types, and invented return schemas. It sends revision notes back to the Writer for up to two rounds, then ships whatever it has.

**Prompt caching:** the manifest JSON is cached across all Writer and Reviewer calls, keeping per-page API costs low after the first call.

**Optional repo enrichment (Phase 2):** point `REPO_PATH` at the server's source repo and the pipeline adds an Ingest step (walks and classifies source files under a token budget) and a Researcher agent (Opus) that produces a structured `research.json`. The Planner then adds architecture, setup, and extension pages, and the Writer gets the research as context for every page. Phase 2 is entirely optional — the pipeline still works against any MCP server with no source access.

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

# Optional: set this to enable Phase 2 repo enrichment
# REPO_PATH=/path/to/cortex-repo
```

## Running

```bash
# Generate docs (Phase 1: protocol-only, no repo required)
REPO_PATH= uv run python3 -m cortexdocs generate --no-eval

# Generate docs with Phase 2 repo enrichment (requires REPO_PATH in .env)
uv run python3 -m cortexdocs generate --no-eval

# Score the generated docs (15 questions × 3 contexts × Opus judge)
uv run python3 -m cortexdocs eval-docs

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

The same commands are wrapped as Makefile targets: `make generate`, `make generate-phase2`, `make eval`, `make serve`, `make deploy`.

## Project status

| Feature | Status |
|---|---|
| MCP discovery (any server) | Done |
| Planner → Writer → Reviewer pipeline | Done |
| MkDocs site rendering | Done |
| Machine artifacts (api.json, llms.txt) | Done |
| GitHub Pages deploy | Done |
| Phase 2: ingest + Researcher (architecture, setup, extension guides) | Done |
| Evaluation harness (blind 3-way judge) | Done |

## Evaluation

`cortexdocs eval-docs` measures whether the generated docs actually help. It asks 15 questions across three difficulty tiers, answering each from three different contexts, then has an Opus judge score the answers blind (labelled A/B/C, with no indication of which context produced which answer) on accuracy, completeness, and conciseness.

| Context | What the answerer sees |
|---|---|
| **A** | The raw manifest only (`api.json`) |
| **B** | Phase 1 docs (`llms-full.txt` with Phase 2 pages stripped) |
| **C** | Phase 1 + Phase 2 docs (full `llms-full.txt`) |

Results against the Cortex server (mean score, 1–5):

| Tier | A | B | C | B−A | C−B |
|---|---|---|---|---|---|
| 1 — parameter lookups | 2.20 | 4.13 | 4.40 | +1.93 | +0.27 |
| 2 — protocol decisions and workflows | 2.53 | 4.40 | 4.33 | +1.87 | −0.07 |
| 3 — implementation internals | 2.67 | 4.40 | 4.53 | +1.73 | +0.13 |
| **All** | **2.47** | **4.31** | **4.42** | **+1.84** | **+0.11** |

The large B−A gap is the main result: structured docs beat the raw schema everywhere, including on Tier 1 questions the manifest technically already answers. The C−B gap is small and only clearly positive on Tier 3, which is what you would expect — repo enrichment pays off on questions about internals and adds little to parameter lookups.

The full report, including per-question scores and worked examples, is written to `output/eval_report.md`.

## Architecture

See [plans/ARCHITECTURE.md](plans/ARCHITECTURE.md) for the full design, data models, and LangGraph graph topology.

See [CLAUDE.md](CLAUDE.md) for AI-agent-oriented documentation: file layout, known quirks, implementation status, and running the project.

## Tech stack

Python · LangGraph · Anthropic API (Sonnet + Opus) · MCP Python SDK · MkDocs Material · pydantic-settings · typer

## What was learned

- **Protocol-first beats code-first for tool discovery.** `tools/list` gives you clean JSON Schema directly; static analysis of TypeScript/Zod gives you parsing headaches and edge cases.
- **The Reviewer earns its token cost.** Without it, the Writer consistently invents plausible-but-wrong return value schemas. The review loop catches this reliably, especially on tools whose descriptions don't specify return types.
- **Prompt caching is essential at scale.** For 21 pages × up to 3 calls each, caching the manifest JSON block reduces costs by roughly 70% after the first page.
- **`--from-stage` iteration is non-negotiable.** Being able to re-run just the write or render stage without re-discovering the server cuts iteration time from minutes to seconds during prompt tuning.
- **Structured docs beat raw schemas by more than expected.** The eval shows a +1.84 average lift over the manifest alone — and the gain holds even on questions the manifest already contains the answer to. Format and surrounding context matter, not just the presence of the facts.
- **Repo enrichment is worth it, but narrowly.** Phase 2 only moves the needle on questions about implementation internals (+0.13 on Tier 3, and the only source of truth for several of them). For protocol-level questions it adds close to nothing — which is a useful argument for keeping Phase 1 usable standalone.
