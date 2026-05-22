#!/usr/bin/env python3
"""Detect when Claude stops and set the appropriate emoji.

If Claude's last response contains a question requiring user input, sets
EMOJI_QUESTION (with sound). Otherwise sets EMOJI_READY (silent).

Tier 2 heuristic: reads the Stop event's `last_assistant_message` field.
If a question mark is found in the last 500 chars, calls local Ollama
model to classify whether Claude is asking for a decision or input.

Pre-filter: skips the LLM call entirely if no '?' in the last 500 chars
(~80% of stops go straight to ready).
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import title_state
from sound_utils import (
    EMOJI_QUESTION,
    EMOJI_READY,
    log,
    set_attention_emoji,
    set_status_emoji,
    skip_subagent_payload,
    strip_all_emojis,
)


def read_debounce(session_id: str) -> tuple[str, str]:
    """Read timestamp and raw title from debounce file."""
    state = title_state.read(session_id)
    if state.has_title:
        return state.timestamp, state.title
    return "0", ""


def strip_emoji(title: str) -> str:
    return strip_all_emojis(title)


def llm_classifies_as_question(text_tail: str, session_id: str = "") -> tuple[bool, str]:
    """Ask local Ollama model if this text is requesting user input/decision.

    Returns (result, reason) where reason explains the outcome for logging.
    """
    system = (
        "Classify: does this text require the user to respond, decide, or provide input "
        "before work can continue? This controls a notification — only answer YES if the "
        "user is expected to act.\n\n"
        'YES: "Which approach do you prefer: A or B?"\n'
        'NO: "Let me know if you have any questions."\n\n'
        "Output exactly YES or NO, nothing else."
    )

    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from client import llm as call_llm

        raw = call_llm(
            text_tail,
            system=system,
            temperature=0,
            max_tokens=5,
            num_ctx=4096,
            tag="stop-question",
            timeout=10,
        )
        answer = raw.strip().upper()
        return answer.startswith("YES"), f"model answered {answer[:10]!r}"
    except Exception as e:
        return False, f"llm error: {e}"


def _set_ready(session_id: str, clean_title: str, timestamp: str) -> None:
    """Set 🌿 ready emoji if a title is established."""
    if not clean_title:
        log(session_id, "stop-q", f"skip {EMOJI_READY}: no established title")
        return
    log(session_id, "stop-q", f"-> {EMOJI_READY} ready ({clean_title!r})")
    set_status_emoji(session_id, EMOJI_READY, clean_title, timestamp, "stop-q")


def main():
    # Guard against recursive execution from nested claude subprocesses
    if os.environ.get("_CLAUDE_HOOK_NESTED"):
        sys.exit(0)

    data = json.load(sys.stdin)
    session_id = data.get("session_id", "unknown")
    if skip_subagent_payload(data, session_id, "stop-q"):
        sys.exit(0)

    # Stop hooks must check this to prevent infinite loops
    if data.get("stop_hook_active"):
        log(session_id, "stop-q", "skip: stop_hook_active")
        sys.exit(0)

    # Use last_assistant_message directly from Stop event data.
    # This is more reliable than parsing the transcript JSONL, which
    # intermittently has an empty/missing transcript_path.
    last_text = data.get("last_assistant_message", "")

    log(session_id, "stop-q", f"fired (msg_len={len(last_text)})")

    timestamp, raw_title = read_debounce(session_id)
    clean_title = strip_emoji(raw_title)

    if not last_text:
        log(session_id, "stop-q", "skip: no last_assistant_message in stop data")
        sys.exit(0)

    # Pre-filter: only call LLM if '?' appears in the last 500 chars
    tail = last_text[-500:]
    if "?" not in tail:
        log(session_id, "stop-q", "no '?' in last 500 chars -> ready")
        _set_ready(session_id, clean_title, timestamp)
        sys.exit(0)

    # Skip if question emoji is already showing (no title change needed)
    if raw_title.startswith(f"{EMOJI_QUESTION} "):
        log(session_id, "stop-q", f"skip: {EMOJI_QUESTION} already showing")
        sys.exit(0)

    log(session_id, "stop-q", f"calling llm (tail={tail[-80:]!r})")
    result, reason = llm_classifies_as_question(tail, session_id)
    log(session_id, "stop-q", f"llm -> {result} ({reason})")
    if not result:
        _set_ready(session_id, clean_title, timestamp)
        sys.exit(0)

    if not clean_title:
        log(session_id, "stop-q", "skip: no established title, won't set emoji")
        sys.exit(0)
    log(session_id, "stop-q", f"-> {EMOJI_QUESTION} question ({clean_title!r})")
    set_attention_emoji(session_id, EMOJI_QUESTION, clean_title, timestamp, "stop-q")
    sys.exit(0)


if __name__ == "__main__":
    main()
