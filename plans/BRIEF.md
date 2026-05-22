# CortexDocs — Project Brief

**Author:** Rob Dixon
**Date:** May 21, 2026
**Status:** Draft v0.2 — for review and refinement before kickoff
**Target completion:** 4 working days from kickoff

---

## 1. Purpose

Build a small, working AI documentation generator that ingests the Cortex MCP server repository and produces a complete documentation set with two audiences in mind: human developers reading rendered web pages, and AI agents consuming machine-optimized variants of the same content.

The project exists for two reasons:

1. **Direct demonstration of capability** and experience using AI tools to streamline content creation, structuring content for AI ingestion, and evaluating documentation quality for AI consumers.
2. **Genuine craft exploration** of how a small multi-agent pipeline can produce documentation that holds up under both reader populations — a question worth answering on its own merits, independent of the job application.

The first version is a working prototype, not a production-ready tool.

---

## 2. Thesis

Most AI-assisted documentation pipelines optimize for one audience and treat the other as a fallback. A pipeline that explicitly produces parallel human-first and machine-first outputs from the same source, and measures the quality of each, makes the audience tradeoffs visible and tunable. This is the right framing for documentation in the agentic era.

---

## 3. Scope

### In scope

- A working pipeline that runs end-to-end via a single command (`pnpm run generate`) and produces:
  - A rendered static documentation site (MkDocs Material or equivalent) covering Cortex's architecture, MCP tools, setup, and developer extension points.
  - Machine-optimized artifacts: `llms.txt`, `llms-full.txt`, structured frontmatter on every page, and a machine-readable API/tool reference (`api.json` or equivalent).
- A three-agent pipeline (Researcher, Writer, Reviewer) with a bounded review loop.
- An evaluation harness that scores how well an LLM can answer developer questions about Cortex when given (a) the human-optimized docs and (b) the machine-optimized variants, with a short comparison report.
- A README that explains what the project is, how to run it, and what was learned.
- A short demo path: from `pnpm install` to viewing the generated docs site locally, in under five minutes for a reviewer who has Node and Python installed.

### Out of scope

- Continuous integration, deployment automation beyond a single static-site deploy.
- Multi-repo support beyond a single optional stress-test run against a second small repo.
- A custom doc-site theme or UI work beyond what the chosen static-site generator provides out of the box.
- Fine-tuning, RAG, or vector retrieval inside the pipeline. The agents operate over the repo directly with whole-file context where it fits, and chunked summaries where it does not.
- Productization concerns: auth, multi-tenancy, billing, persistent storage.
- Polishing the generated docs by hand before demo. The output stands or falls on the pipeline.

### Explicit non-goal

Beating hand-written docs on quality. The goal is to produce docs good enough that a developer could actually use them to work with Cortex, and to make the human/machine audience tradeoff visible. "Good enough to use" is the bar, not "indistinguishable from a human technical writer."

---

## 4. Success criteria

The project is successful if, at the end of four working days, all of the following are true:

1. A reviewer can clone the repo, run `pnpm install && pnpm run generate`, and produce both the human site and the machine artifacts without manual intervention.
2. The generated docs site contains at minimum: an overview, an architecture page, a per-MCP-tool reference, a setup guide, and an extension guide for adding new tools.
3. The machine-optimized artifacts conform to the `llms.txt` convention and are valid markdown.
4. The eval harness runs against 10-15 developer questions and produces a comparison report showing which audience variant performed better on which questions, with reference answers I wrote by hand.
5. The README clearly states what the project does, what was learned, and the limits of the approach. A reader gets the point in under three minutes.
6. I can demo the project live in 5-7 minutes without anything breaking.

The project is a partial success (still presentable) if (1) through (3) hold but (4) is incomplete or messy.

The project should be reconsidered if by end of day 2 the agent chain is not yet producing one good doc page end-to-end.

---

## 5. Architecture

### Pipeline

```
Cortex repo
    │
    ▼
[Ingest]  walk files, classify, extract MCP tool definitions
    │
    ▼
[Researcher agent]  produce structured codebase summary (JSON)
    │
    ▼
[Writer agent]  produce doc plan, then write each page
    │      ▲
    ▼      │
[Reviewer agent]  approve, or return revision notes (max N iterations)
    │
    ▼
[Render]  → human site (MkDocs Material)
          → machine artifacts (llms.txt, llms-full.txt, frontmatter, api.json)
    │
    ▼
[Eval]   developer Qs → LLM answers using each variant → LLM-as-judge → report
```

### Agent responsibilities

- **Researcher.** Walks the repo, classifies files, extracts MCP tool definitions as first-class entities, summarizes each module. Output is structured JSON, not prose. This is the foundation — every downstream agent reads its output, never the raw repo.
- **Writer.** Reads the Researcher's output, produces a documentation plan (page list, intended audience per page, key points), then writes each page as markdown with structured frontmatter.
- **Reviewer.** Reads each generated page against the Researcher's output. Approves, or returns specific revision notes (max two revision rounds per page, then ship what we have). Reviewer has explicit instructions to look for: factual errors against source, missing critical information, audience-mismatch issues, and machine-readability issues in the frontmatter.

### Key design constraints

- Whole-file context where files fit in the model's context window; chunked summaries otherwise. No vector retrieval — this project is about agent orchestration, not RAG.
- Bounded loops on the Reviewer. If it has not approved by iteration N, ship what we have with a flag in the page metadata. Unbounded review loops are a known failure mode of this pattern.
- Sonnet for high-volume work (Writer), Opus for judgment work (Reviewer and eval judge). Reconsider per cost after day 2.
- Every agent call is logged to disk with input, output, and token usage. The logs are part of the deliverable — they make the pipeline auditable and demoable.

---

## 6. Toolset

| Concern | Choice | Why |
|---|---|---|
| Language | TypeScript | Matches Cortex; fastest path for me |
| LLM | Anthropic API (Sonnet 4.5 + Opus 4.7) | Default; aligns with hiring context |
| Agent framework | **Decision pending** — see §7 | Two real options |
| Code parsing | Whole-file to Claude; tree-sitter only if needed | Avoid premature complexity |
| Human site | MkDocs Material | Fastest path to a beautiful static site |
| Machine artifacts | `llms.txt` convention, hand-rolled | No tooling needed; it's just markdown |
| Eval | Hand-rolled harness, ~100 lines | Full control; demoable; understandable |
| Hosting | GitHub Pages or Vercel for the rendered site | Single command deploy |
| Logging | Local JSON log per agent run | Auditable, inspectable, demo asset |

---

## 7. Open decisions before kickoff

These need to be resolved before day 1 begins.

1. **Agent framework.** LangGraph (real learning credential, transfers to other projects, half-day learning tax) versus rolling my own with the Anthropic SDK (fastest, lowest risk, less impressive on the resume). My current lean: **LangGraph**, because it's already in my learning plan and a real project is the best way to learn it. Reconsider if day 1 reveals friction.
2. **Project name.** "CortexDocs" is the working title. Acceptable, or pick something better.
3. **Optional stress test.** Should I reserve half of day 4 to run the pipeline against a second small repo as a generality demonstration? Strongly tempted; depends on day 3 timing.

---

## 8. Day-by-day plan

Phased so that Option A (basic multi-agent generator) is shippable at any point, and Option B (with dual-audience output and eval) is what we aim for.

### Day 1 — Ingestion and Researcher agent

- Set up the repo, framework decision, and basic project structure.
- Build the repo ingestion step: file walk, classification, MCP tool extraction.
- Get the Researcher agent producing structured JSON describing the Cortex codebase.
- End-of-day target: `pnpm run research` produces a complete `research.json` for Cortex.

### Day 2 — Writer, Reviewer, first end-to-end doc

- Build the Writer agent. Produce a doc plan from `research.json`, then write the first page.
- Build the Reviewer agent. Wire up the bounded review loop.
- Generate v1 of all pages as plain markdown (no rendering yet, no machine variants).
- End-of-day target: a complete set of generated markdown pages on disk. **This is the Option A shippable point.** If everything after this fails, the project still demonstrates the agentic pipeline.

### Day 3 — Dual-audience output and rendering

- Add structured frontmatter to every page (Writer agent update).
- Generate machine artifacts: `llms.txt`, `llms-full.txt`, `api.json`.
- Set up MkDocs Material, theme it minimally, render the human site.
- Deploy the rendered site somewhere a reviewer can click.
- End-of-day target: a live URL showing the human docs, and the machine artifacts available in the repo.

### Day 4 — Evaluation harness, polish, demo prep

- Write 10-15 developer questions about Cortex with reference answers (manual).
- Build the eval harness: for each question, ask an LLM to answer using each context variant, judge with a separate LLM call, log all results.
- Generate the comparison report as a markdown file in the repo.
- Polish README, write a short "what I learned" section.
- Practice the 5-7 minute demo end-to-end.

### Built-in slack

If day 1 or day 2 slips by half a day, drop the stress-test second repo. If they slip by a full day, ship Option A (no eval, no machine variants) and write up what would come next. The project must be demoable on day 4 regardless.

---

## 9. Risks and what we'll do about them

| Risk | Likelihood | Mitigation |
|---|---|---|
| Agent loop oscillates or never converges | High | Hard iteration cap; ship-with-flag fallback; instrument early |
| LangGraph learning curve eats day 1 | Medium | Pre-decide a fallback to roll-your-own by end of day 1 morning if friction is real |
| Generated docs are factually wrong about Cortex | Medium | Reviewer explicitly checks against Researcher output; I spot-check on day 4 |
| Eval results are uninteresting (both variants score the same) | Medium | That's still a valid finding — write up the result honestly; don't fake a tradeoff |
| API costs spiral | Low | Token-budget logging from day 1; switch to Sonnet for Reviewer if costs run hot |
| Day 4 demo breaks live | Low | Recorded backup video on the morning of day 4 |

---

## 10. What this project is not

A few things worth stating plainly so they do not get scope-crept in later:

- It is not a product. There is no business model, no users, no roadmap beyond the four-day build.
- It is not a general-purpose doc generator. It is a project that happens to work on Cortex, and we will demonstrate it works on one other repo if time allows.
- It is not a replacement for a technical writer. The thesis is that an agentic pipeline can produce useful first-draft documentation and machine-consumable variants, not that it can replace the judgment a senior writer brings.
- It is not a research paper. The eval is real but small. Findings are illustrative, not statistically meaningful.

---

## 11. What success looks like

I can open my laptop, show the rendered docs site, walk through one page, show the corresponding `llms.txt` entry, run a single eval question live (or play a recorded run), and show the comparison report. Total time: 5-7 minutes.

The conversation I want this to enable: "How would you apply this thinking to our developer documentation?"
