"""Evaluation harness.

For each question, asks three variants of the docs context:
  A — manifest only (api.json)
  B — Phase 1 docs  (llms-full.txt, no research pages)
  C — Phase 1+2 docs (llms-full.txt, includes architecture/setup/extending)

The judge sees A/B/C labels only — no "manifest" or "Phase 1" labels — so the
comparison is blind with respect to which context produced which answer.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import anthropic
from rich.console import Console

from cortexdocs.config import Settings
from cortexdocs.eval.judge import judge
from cortexdocs.eval.questions import EvalQuestion, QUESTIONS

console = Console()

_ANSWERER_SYSTEM = """\
You are a helpful technical assistant. Answer the question using ONLY the documentation \
provided. If the documentation does not contain enough information to answer confidently, \
say so clearly rather than guessing. Be concise — 2–5 sentences or a short bullet list. \
Do not pad the answer.
"""


@dataclass
class QuestionResult:
    question: EvalQuestion
    answer_a: str   # manifest only
    answer_b: str   # Phase 1 docs
    answer_c: str   # Phase 1+2 docs
    scores: list[dict] = field(default_factory=list)  # from judge


def _ask(question: str, context: str, client: anthropic.Anthropic, model: str) -> str:
    """Ask the question against a single context document."""
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=_ANSWERER_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": f"Documentation:\n\n{context}\n\n---\n\nQuestion: {question}",
            }
        ],
    )
    return response.content[0].text.strip()


def _load_context_a(output_dir: Path) -> str:
    """Manifest / api.json — tier 1 context."""
    api_path = output_dir / "api.json"
    if not api_path.exists():
        raise FileNotFoundError(f"api.json not found at {api_path}. Run 'generate' first.")
    data = json.loads(api_path.read_text())
    # Flatten to a readable text block
    lines = [f"# {data.get('server_name', 'MCP Server')} — Tool Reference\n"]
    for tool in data.get("tools", []):
        lines.append(f"## {tool['name']}")
        lines.append(tool.get("description", ""))
        params = tool.get("parameters", {}).get("properties", {})
        required = tool.get("parameters", {}).get("required", [])
        if params:
            lines.append("Parameters:")
            for name, schema in params.items():
                req = " (required)" if name in required else " (optional)"
                lines.append(f"  - {name}{req}: {schema.get('description', schema.get('type', ''))}")
        lines.append("")
    return "\n".join(lines)


def _load_context_b(output_dir: Path) -> str:
    """Phase 1 llms-full.txt — excludes Phase 2 pages."""
    full_path = output_dir / "llms-full.txt"
    if not full_path.exists():
        raise FileNotFoundError(f"llms-full.txt not found at {full_path}. Run 'generate' first.")
    content = full_path.read_text()
    # Strip architecture/setup/extending pages to isolate Phase 1 content
    phase2_markers = [
        "# Architecture",
        "# Setup Guide",
        "# Extension Guide",
    ]
    for marker in phase2_markers:
        idx = content.find(f"\n{marker}")
        if idx != -1:
            content = content[:idx]
    return content.strip()


def _load_context_c(output_dir: Path) -> str:
    """Phase 1+2 llms-full.txt — full content."""
    full_path = output_dir / "llms-full.txt"
    if not full_path.exists():
        raise FileNotFoundError(f"llms-full.txt not found at {full_path}. Run 'generate' first.")
    return full_path.read_text()


def run_eval(settings: Settings) -> list[QuestionResult]:
    """Run the full evaluation. Returns results for all questions."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    output_dir = settings.output_dir

    console.print("[bold]Eval:[/bold] Loading contexts...")
    ctx_a = _load_context_a(output_dir)
    ctx_b = _load_context_b(output_dir)
    ctx_c = _load_context_c(output_dir)

    # Warn if Phase 2 pages are not present (context B == context C)
    if ctx_b == ctx_c:
        console.print(
            "[yellow]Warning:[/yellow] Phase 2 pages (architecture/setup/extending) not found in "
            "llms-full.txt — context B and C will be identical. Run full Phase 2 generate first."
        )

    results: list[QuestionResult] = []

    for i, q in enumerate(QUESTIONS, 1):
        console.print(f"[bold]Eval:[/bold] Q{i}/{len(QUESTIONS)} [dim](tier {q.tier})[/dim] {q.question[:60]}...")

        answer_a = _ask(q.question, ctx_a, client, settings.writer_model)
        answer_b = _ask(q.question, ctx_b, client, settings.writer_model)
        answer_c = _ask(q.question, ctx_c, client, settings.writer_model)

        console.print(f"  [dim]Judging...[/dim]")
        scores, _ = judge(q, answer_a, answer_b, answer_c, client, settings.judge_model)

        result = QuestionResult(
            question=q,
            answer_a=answer_a,
            answer_b=answer_b,
            answer_c=answer_c,
            scores=scores,
        )
        results.append(result)

        # Show a quick summary line
        score_map = {s["label"]: s for s in scores}
        avg = lambda s: round((s["accuracy"] + s["completeness"] + s["conciseness"]) / 3, 1)
        console.print(
            f"  A={avg(score_map['A'])}  B={avg(score_map['B'])}  C={avg(score_map['C'])}"
        )

    return results
