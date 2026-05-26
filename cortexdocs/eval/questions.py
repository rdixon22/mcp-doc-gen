from dataclasses import dataclass
from typing import Literal


@dataclass
class EvalQuestion:
    id: str
    tier: Literal[1, 2, 3]
    question: str
    # What the ideal answer would cover — used by the judge as a rubric hint
    expected_coverage: str


QUESTIONS: list[EvalQuestion] = [
    # ------------------------------------------------------------------
    # Tier 1 — answerable from manifest alone (api.json)
    # ------------------------------------------------------------------
    EvalQuestion(
        id="t1-q1",
        tier=1,
        question="What parameters does `capture_thought` accept, and which are required?",
        expected_coverage=(
            "Should list all parameters (content, type, source, topics, people, metadata), "
            "identify required vs optional, and note their types."
        ),
    ),
    EvalQuestion(
        id="t1-q2",
        tier=1,
        question="Which tools accept a `limit` parameter to control the number of results returned?",
        expected_coverage=(
            "Should identify search_thoughts, list_thoughts, search_messages, search_wiki, "
            "list_wiki_pages, search_all as having a limit parameter."
        ),
    ),
    EvalQuestion(
        id="t1-q3",
        tier=1,
        question="What is the difference between `search_thoughts` and `search_all` in terms of what they search?",
        expected_coverage=(
            "search_thoughts searches captured notes only; search_all searches both thoughts "
            "and WikiVault pages together. Should note the broader scope of search_all."
        ),
    ),
    EvalQuestion(
        id="t1-q4",
        tier=1,
        question="Does the Cortex MCP server expose any resources or prompts, or only tools?",
        expected_coverage=(
            "Should correctly answer that the server exposes only tools (16 tools), "
            "no MCP resources or prompts."
        ),
    ),
    EvalQuestion(
        id="t1-q5",
        tier=1,
        question="What does the `dry_run` parameter do in `batch_migrate_vault`, and what type does it accept?",
        expected_coverage=(
            "Should explain dry_run is boolean, optional, defaults to false, and when true "
            "reports what would be migrated without actually moving files."
        ),
    ),

    # ------------------------------------------------------------------
    # Tier 2 — need Phase 1 docs (llms-full.txt, protocol-level knowledge)
    # ------------------------------------------------------------------
    EvalQuestion(
        id="t2-q1",
        tier=2,
        question="When should I use `search_wiki` versus `list_wiki_pages` to find a WikiVault page?",
        expected_coverage=(
            "search_wiki for semantic/conceptual lookups when you know the topic but not the "
            "exact title; list_wiki_pages for enumeration by type/status or when you want a "
            "full listing. Should mention the decision guidance."
        ),
    ),
    EvalQuestion(
        id="t2-q2",
        tier=2,
        question="What is the recommended sequence of calls to safely create or update a WikiVault page?",
        expected_coverage=(
            "Should describe the read-before-write protocol: (1) read_wiki_page or search_wiki "
            "first to check if a page exists, (2) then write_wiki_page. Possibly (3) "
            "append_wiki_log afterward."
        ),
    ),
    EvalQuestion(
        id="t2-q3",
        tier=2,
        question="What does `wiki_health` check for, and what issues can it automatically fix?",
        expected_coverage=(
            "Should list the checks (bad frontmatter, dead wikilinks, orphaned pages, "
            "duplicate titles) and explain which can be auto-fixed vs reported only."
        ),
    ),
    EvalQuestion(
        id="t2-q4",
        tier=2,
        question="How do I perform a dry run before executing `batch_migrate_vault` on a real directory?",
        expected_coverage=(
            "Should explain passing dry_run=true, what the response contains in dry run mode, "
            "and recommend reviewing the report before running without dry_run."
        ),
    ),
    EvalQuestion(
        id="t2-q5",
        tier=2,
        question="What happens when the `ingest_to_wiki` librarian agent exceeds `max_iterations`?",
        expected_coverage=(
            "Should explain the agent stops, the page is left with librarian_status: interrupted "
            "or similar, and process_raw_inbox can be used to resume/retry."
        ),
    ),

    # ------------------------------------------------------------------
    # Tier 3 — need Phase 2 docs (repo-enriched: architecture, setup, impl)
    # ------------------------------------------------------------------
    EvalQuestion(
        id="t3-q1",
        tier=3,
        question="What database does Cortex use to store thoughts, and how is the data schema structured?",
        expected_coverage=(
            "Should name Supabase/PostgreSQL, describe the thoughts table structure "
            "(content, type, embedding vector, metadata, topics, people), and mention "
            "pgvector for semantic search."
        ),
    ),
    EvalQuestion(
        id="t3-q2",
        tier=3,
        question="How does Cortex generate embeddings, and what model or service does it use?",
        expected_coverage=(
            "Should describe the embedding pipeline — which model is used (Ollama local model), "
            "when embeddings are generated (on capture_thought), and how they enable semantic search."
        ),
    ),
    EvalQuestion(
        id="t3-q3",
        tier=3,
        question="What is the architectural difference between the stdio and HTTP transports in this server?",
        expected_coverage=(
            "Should explain that mcp-stdio.ts and the HTTP transport expose the same tools "
            "but differ in how they receive connections — stdio for local MCP clients, "
            "HTTP for remote/web access. Should reference the relevant source files."
        ),
    ),
    EvalQuestion(
        id="t3-q4",
        tier=3,
        question="How does the librarian agent in `ingest_to_wiki` work internally — what is its control flow?",
        expected_coverage=(
            "Should explain the agent loop: reads source document, searches existing wiki pages "
            "for related content, decides whether to create/update/merge, writes the page, "
            "logs the action. Should reference the implementation file."
        ),
    ),
    EvalQuestion(
        id="t3-q5",
        tier=3,
        question="How would a developer add a new MCP tool to this server — what files need to change and in what order?",
        expected_coverage=(
            "Should describe: (1) implement handler function in the relevant route/handler file, "
            "(2) register the tool in the MCP server registration file with name/description/schema, "
            "(3) optionally add tests. Should reference the registration pattern and relevant files."
        ),
    ),
]
