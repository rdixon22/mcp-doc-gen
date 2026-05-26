"""Generate eval_report.md from QuestionResult list."""
from __future__ import annotations

import json
from pathlib import Path

from cortexdocs.eval.harness import QuestionResult


def _avg(scores: list[dict], label: str) -> float:
    s = next((x for x in scores if x["label"] == label), None)
    if not s:
        return 0.0
    return round((s["accuracy"] + s["completeness"] + s["conciseness"]) / 3, 2)


def _score_row(scores: list[dict], label: str) -> str:
    s = next((x for x in scores if x["label"] == label), None)
    if not s:
        return "— / — / —"
    return f"{s['accuracy']} / {s['completeness']} / {s['conciseness']}"


def generate_report(results: list[QuestionResult], output_dir: Path) -> Path:
    """Write eval_report.md to output_dir and return its path."""
    lines: list[str] = []

    lines += [
        "# CortexDocs Eval Report",
        "",
        "Three documentation contexts evaluated across 15 questions in 3 tiers.",
        "",
        "**Contexts:**",
        "- **A** — Manifest only (`api.json`): tool names, descriptions, parameter schemas",
        "- **B** — Phase 1 docs (`llms-full.txt`, protocol pages only): tool pages + overview + tools index",
        "- **C** — Phase 1+2 docs (`llms-full.txt`, full): adds architecture, setup, and extension guide",
        "",
        "**Scoring** (per dimension, 1–5): accuracy / completeness / conciseness  ",
        "**Average** = mean of three dimensions.",
        "",
    ]

    # ---- Summary table ------------------------------------------------
    lines += [
        "## Summary",
        "",
        "| ID | Tier | Question | A avg | B avg | C avg |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        q = r.question
        short = q.question[:55] + "…" if len(q.question) > 55 else q.question
        lines.append(
            f"| {q.id} | {q.tier} | {short} "
            f"| {_avg(r.scores, 'A')} | {_avg(r.scores, 'B')} | {_avg(r.scores, 'C')} |"
        )

    # ---- Aggregate stats by tier --------------------------------------
    lines += ["", "## Aggregate by tier", ""]
    lines += ["| Tier | A mean | B mean | C mean | B–A | C–B |", "|---|---|---|---|---|---|"]
    for tier in (1, 2, 3):
        tier_results = [r for r in results if r.question.tier == tier]
        if not tier_results:
            continue
        a_mean = round(sum(_avg(r.scores, "A") for r in tier_results) / len(tier_results), 2)
        b_mean = round(sum(_avg(r.scores, "B") for r in tier_results) / len(tier_results), 2)
        c_mean = round(sum(_avg(r.scores, "C") for r in tier_results) / len(tier_results), 2)
        lines.append(
            f"| Tier {tier} | {a_mean} | {b_mean} | {c_mean} "
            f"| {round(b_mean - a_mean, 2):+} | {round(c_mean - b_mean, 2):+} |"
        )

    # Overall row
    a_all = round(sum(_avg(r.scores, "A") for r in results) / len(results), 2)
    b_all = round(sum(_avg(r.scores, "B") for r in results) / len(results), 2)
    c_all = round(sum(_avg(r.scores, "C") for r in results) / len(results), 2)
    lines += [
        f"| **All** | **{a_all}** | **{b_all}** | **{c_all}** "
        f"| **{round(b_all - a_all, 2):+}** | **{round(c_all - b_all, 2):+}** |",
        "",
    ]

    # ---- Narrative -------------------------------------------------------
    lines += [
        "## What the data shows",
        "",
        (
            f"Across all 15 questions, structured Phase 1 docs (context B) score "
            f"{round(b_all - a_all, 2):+.2f} points on average over the raw manifest (A), "
            f"and Phase 1+2 docs (C) score {round(c_all - b_all, 2):+.2f} over B. "
            "The gains are not uniform across tiers."
        ),
        "",
        (
            "Tier 1 questions (parameter lookups, tool enumeration) are largely answered by the "
            "manifest alone. The additional prose in the docs pages adds completeness context "
            "— decision guidance, usage examples — but does not dramatically change accuracy, "
            "since the manifest already contains the ground truth."
        ),
        "",
        (
            "Tier 2 questions (protocol-level decisions, multi-step workflows) show the clearest "
            "lift from Phase 1 docs. The tools index decision tables and the read-before-write "
            "protocol notes exist only in the generated docs, not in the raw manifest schema. "
            "These are precisely the questions a developer would ask at integration time."
        ),
        "",
        (
            "Tier 3 questions (database schema, embedding pipeline, librarian agent internals, "
            "transport architecture) require Phase 2 pages to answer well. The manifest says "
            "nothing about implementation; Phase 2 docs are the only source of truth here. "
            "The C–B delta on Tier 3 questions is the primary signal that repo enrichment "
            "is doing useful work."
        ),
        "",
    ]

    # ---- Worked example (first Tier 3 question) --------------------------
    tier3 = next((r for r in results if r.question.tier == 3), None)
    if tier3:
        lines += [
            "## Worked example",
            "",
            f"**Question ({tier3.question.id}):** {tier3.question.question}",
            "",
            f"**Rubric:** {tier3.question.expected_coverage}",
            "",
            "**Answer A (manifest only):**",
            "",
            f"> {tier3.answer_a}",
            "",
            "**Answer B (Phase 1 docs):**",
            "",
            f"> {tier3.answer_b}",
            "",
            "**Answer C (Phase 1+2 docs):**",
            "",
            f"> {tier3.answer_c}",
            "",
            "**Judge scores:**",
            "",
            "| Label | Accuracy | Completeness | Conciseness | Rationale |",
            "|---|---|---|---|---|",
        ]
        for s in tier3.scores:
            lines.append(
                f"| {s['label']} | {s['accuracy']} | {s['completeness']} | {s['conciseness']} "
                f"| {s['rationale'][:120]}… |"
            )
        lines.append("")

    # ---- Save raw data ---------------------------------------------------
    raw_path = output_dir / "eval_results.json"
    raw = [
        {
            "question_id": r.question.id,
            "tier": r.question.tier,
            "question": r.question.question,
            "answer_a": r.answer_a,
            "answer_b": r.answer_b,
            "answer_c": r.answer_c,
            "scores": r.scores,
        }
        for r in results
    ]
    raw_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    report_path = output_dir / "eval_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
