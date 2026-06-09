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
        "Classify whether the first user prompt should enter the CHECK workflow state.\n"
        "Output CHECK when the immediate goal is to sanity-check, ticket-check, inspect, or review something before deciding whether to prep, plan, or implement.\n"
        "Output NONE for ordinary questions, direct implementation requests, explicit /plan or prep requests, or any prompt already asking for the next phase.\n"
        "Positive examples:\n"
        "- 'Can you sanity check MIN-180 before I plan it?' -> CHECK\n"
        "- 'Review this branch and tell me if the PRD is worth writing' -> CHECK\n"
        "- 'Can you check whether this idea is worth planning?' -> CHECK\n"
        "Negative examples:\n"
        "- 'Implement the login fix' -> NONE\n"
        "- '/plan-quick this PRD' -> NONE\n"
        "- 'Write the product requirements doc' -> NONE\n"
        "- 'What are the current workflow title rules?' -> NONE\n"
        "Final answer must be only CHECK or NONE. Choose CHECK only for check/review-before-next-phase intent."
    ),
    "check-to-prep": (
        "Classify whether a checked workstream should move to PREP.\n"
        "Output PREP when the user asks to turn the check findings into prep, PRD, product understanding, requirements, or shared context for the same workstream.\n"
        "Output NONE when the user is asking more check questions, asking what you found, revising the check, or explicitly says not to write prep yet.\n"
        "Examples:\n"
        "- 'Good, turn this into a PRD' -> PREP\n"
        "- 'Write the product understanding doc from those findings' -> PREP\n"
        "- 'What did you find?' -> NONE\n"
        "- 'Keep checking; don't write the PRD yet' -> NONE\n"
        "Final answer must be only PREP or NONE."
    ),
    "plan-to-cook": (
        "Classify whether a planned workstream should move to COOK/implementation.\n"
        "Output COOK when the latest message approves the plan and asks to implement, proceed, build, make the changes, or start coding the current plan.\n"
        "Output NONE when the user only asks to revise the plan, update docs, discuss risks, ask questions, or wait for approval.\n"
        "Examples:\n"
        "- 'Looks good, implement it' -> COOK\n"
        "- 'Everything else looks good, proceed with implementing' -> COOK\n"
        "- 'Make these final doc tweaks too, then go ahead and implement' -> COOK\n"
        "- 'Update the PRD and ADR only; don't implement yet' -> NONE\n"
        "- 'Revise the plan with these concerns' -> NONE\n"
        "Final answer must be only COOK or NONE."
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
