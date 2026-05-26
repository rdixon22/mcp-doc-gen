"""Blind 3-way judge using Opus.

The judge receives three answers labelled A / B / C — no context labels visible —
and scores each 1–5 for accuracy, completeness, and conciseness.
"""
import json

import anthropic

from cortexdocs.eval.questions import EvalQuestion

_SYSTEM_PROMPT = """\
You are an expert technical evaluator assessing the quality of answers to questions about \
an MCP (Model Context Protocol) server called Cortex.

You will receive a question, a rubric hint describing what a good answer should cover, \
and three answers labelled A, B, and C. You must score each answer independently \
on three dimensions (1–5 scale):

- accuracy: Is the information correct? Penalise hallucinated details or wrong claims.
- completeness: Does it cover the key points from the rubric? Penalise omissions.
- conciseness: Is it appropriately brief without padding? Penalise excessive waffle.

Output ONLY a JSON object using the score_answers tool. No prose outside the tool call.
"""

_TOOL_DEF = {
    "name": "score_answers",
    "description": "Submit scores for three answers to the evaluation question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "label":        {"type": "string", "enum": ["A", "B", "C"]},
                        "accuracy":     {"type": "integer", "minimum": 1, "maximum": 5},
                        "completeness": {"type": "integer", "minimum": 1, "maximum": 5},
                        "conciseness":  {"type": "integer", "minimum": 1, "maximum": 5},
                        "rationale":    {"type": "string"},
                    },
                    "required": ["label", "accuracy", "completeness", "conciseness", "rationale"],
                },
            }
        },
        "required": ["scores"],
    },
}


def judge(
    question: EvalQuestion,
    answer_a: str,
    answer_b: str,
    answer_c: str,
    client: anthropic.Anthropic,
    model: str,
) -> list[dict]:
    """Score answers A/B/C for a single question. Returns list of score dicts."""
    user_content = (
        f"**Question:** {question.question}\n\n"
        f"**Rubric (what a good answer should cover):** {question.expected_coverage}\n\n"
        f"---\n\n"
        f"**Answer A:**\n{answer_a}\n\n"
        f"**Answer B:**\n{answer_b}\n\n"
        f"**Answer C:**\n{answer_c}"
    )

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        tools=[_TOOL_DEF],
        tool_choice={"type": "tool", "name": "score_answers"},
    )

    tool_block = next(b for b in response.content if b.type == "tool_use")
    scores: list[dict] = tool_block.input["scores"]

    return scores, response.usage
