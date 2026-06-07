"""Local-LLM Transition Judgment for Canonical Workflow Mode.

The classifier returns only workflow transitions. It never produces task slugs;
slug selection remains in the workflow model/tab-title path.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import sys


@dataclass(frozen=True)
class JudgmentContext:
    kind: str
    prompt: str
    current_state: str = ""
    current_title: str = ""
    origin_message: str = ""
    recent_messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class JudgmentResult:
    transition: str = ""


_ALLOWED = {
    "ordinary-to-check": "check",
    "check-to-prep": "prep",
    "plan-to-cook": "cook",
}

_PROMPTS = {
    "ordinary-to-check": (
        "Decide whether the first user prompt starts a developer workstream whose immediate goal is a sanity check, ticket check, or review-before-planning check. "
        "Output CHECK only when it should enter the check workflow state. Otherwise output NONE."
    ),
    "check-to-prep": (
        "Decide whether the follow-up asks to produce prep/PRD/product-understanding work for the current checked workstream. "
        "Output PREP only for that transition. Otherwise output NONE."
    ),
    "plan-to-cook": (
        "Decide whether the follow-up asks to implement/cook the current plan. "
        "Output COOK only for that transition. Otherwise output NONE."
    ),
}


def judge(context: JudgmentContext) -> JudgmentResult:
    target = _ALLOWED.get(context.kind)
    if not target:
        return JudgmentResult()
    try:
        raw = call_llm(_user_message(context), system=_PROMPTS[context.kind])
    except Exception:
        return JudgmentResult()
    return JudgmentResult(parse_transition(raw, target))


def parse_transition(raw: str, allowed_transition: str) -> str:
    if not isinstance(raw, str):
        return ""
    token = raw.strip().strip('"`').lower()
    if token in {"", "none", "no", "uncertain", "unknown", "maybe", "n/a"}:
        return ""
    return allowed_transition if token == allowed_transition else ""


def call_llm(user_message: str, system: str) -> str:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from client import llm

    return llm(
        user_message,
        system=system,
        temperature=0,
        max_tokens=5,
        num_ctx=4096,
        tag="workflow-transition",
        timeout=5,
    )


def _user_message(context: JudgmentContext) -> str:
    parts = [
        f"<current_state>{context.current_state or 'none'}</current_state>",
        f"<current_title>{context.current_title or 'none'}</current_title>",
    ]
    if context.origin_message:
        parts.append(f"<title_origin>{context.origin_message}</title_origin>")
    for message in context.recent_messages:
        if message:
            parts.append(f"<recent_message>{message}</recent_message>")
    parts.append(f"<current_message>{context.prompt}</current_message>")
    parts.append("Output only the allowed token:")
    return "\n".join(parts)
