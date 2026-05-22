#!/usr/bin/env python3
"""Manage Ghostty tab attention state when Claude needs user input.

Open-time signals:
- PreToolUse:AskUserQuestion/question -> EMOJI_QUESTION (before the dialog appears)
- PermissionRequest                   -> EMOJI_BLOCKED (real tool permission block)
  Note: question tools can also fire PermissionRequest, but we skip them here
  since PreToolUse already handles them with the correct EMOJI_QUESTION.

Clear-time signals:
- PostToolUse:AskUserQuestion/question -> clear any attention emoji, restore EMOJI_WORKING
- PostToolUse:*                        -> clear EMOJI_BLOCKED only (permission was accepted)

The emoji is also stripped by the UserPromptSubmit hook (tabtitle-hook.py)
when the user sends their next message.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import title_state
from sound_utils import (
    ALL_EMOJIS,
    EMOJI_BLOCKED,
    EMOJI_QUESTION,
    EMOJI_WORKING,
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


def write_debounce(session_id: str, timestamp: str, title: str, plan_state: str = "") -> None:
    try:
        title_state.write(session_id, timestamp, title, plan_state=plan_state)
    except OSError:
        pass


QUESTION_TOOLS = {"AskUserQuestion", "question"}


def is_question_tool(tool: str) -> bool:
    """Return True for Claude Code and Pi question tool names."""
    return tool in QUESTION_TOOLS


def strip_emoji(title: str) -> str:
    """Remove any leading status emoji from title."""
    return strip_all_emojis(title)


def has_any_emoji(title: str) -> bool:
    return any(title.startswith(emoji) for emoji in ALL_EMOJIS)


def main():
    # Guard against recursive execution from claude -p subprocesses
    if os.environ.get("_CLAUDE_HOOK_NESTED"):
        sys.exit(0)

    data = json.load(sys.stdin)
    event = data.get("hook_event_name", "")
    session_id = data.get("session_id", "unknown")
    if skip_subagent_payload(data, session_id, "attention"):
        sys.exit(0)

    timestamp, raw_title = read_debounce(session_id)
    clean_title = strip_emoji(raw_title)

    # Determine which action to take
    if event == "PreToolUse":
        tool = data.get("tool_name", "")
        if not is_question_tool(tool):
            log(session_id, "attention", f"skip: PreToolUse for non-target tool={tool!r}")
            sys.exit(0)
        log(session_id, "attention", f"PreToolUse:{tool} title={raw_title!r}")
        emoji = EMOJI_QUESTION
    elif event == "PermissionRequest":
        tool = data.get("tool_name", "")
        log(session_id, "attention", f"PermissionRequest:{tool} title={raw_title!r}")
        # Question tools can fire both PreToolUse and PermissionRequest;
        # PreToolUse handles them with ⭐, so skip here to avoid double sound
        if is_question_tool(tool):
            log(session_id, "attention", f"skip: {tool} handled by PreToolUse")
            sys.exit(0)
        emoji = EMOJI_BLOCKED
        # Don't override an existing attention emoji (🔥 or ⭐), but DO replace 🌀 (working)
        if raw_title.startswith(f"{EMOJI_BLOCKED} ") or raw_title.startswith(f"{EMOJI_QUESTION} "):
            log(session_id, "attention", f"skip: attention emoji already set, won't override with {EMOJI_BLOCKED}")
            sys.exit(0)
    elif event == "Notification":
        notification_type = data.get("notification_type", "")
        log(session_id, "attention", f"Notification:{notification_type} title={raw_title!r}")
        if notification_type == "elicitation_dialog":
            emoji = EMOJI_QUESTION
        else:
            log(session_id, "attention", f"skip: unhandled notification_type={notification_type!r}")
            sys.exit(0)
    elif event == "PostToolUse":
        tool = data.get("tool_name", "")
        log(session_id, "attention", f"PostToolUse:{tool} title={raw_title!r}")

        if not has_any_emoji(raw_title):
            log(session_id, "attention", "skip: no emoji to clear")
            sys.exit(0)
        # Question tools clear any attention emoji (⭐ or 🔥)
        # Other tools only clear 🔥 (means permission was accepted)
        if not is_question_tool(tool) and not raw_title.startswith(f"{EMOJI_BLOCKED} "):
            log(session_id, "attention", f"skip: non-question tool, emoji is not {EMOJI_BLOCKED}")
            sys.exit(0)
        if not clean_title:
            log(session_id, "attention", "skip: no established title to restore")
            sys.exit(0)
        # Restore 🌀 working emoji — Claude is still processing after permission accepted
        set_status_emoji(session_id, EMOJI_WORKING, clean_title, timestamp, "attention")
        log(session_id, "attention", f"cleared attention -> {EMOJI_WORKING} {clean_title!r}")
        sys.exit(0)
    else:
        log(session_id, "attention", f"skip: unhandled event={event!r}")
        sys.exit(0)

    # No established title for this session — don't clobber the tab with a generic name
    if not clean_title:
        log(session_id, "attention", "skip: no established title, won't set emoji")
        sys.exit(0)

    # Skip if this emoji is already showing (no title change needed)
    if raw_title.startswith(f"{emoji} ") or raw_title.startswith(f"{emoji}\t"):
        log(session_id, "attention", f"skip: {emoji} already showing")
        sys.exit(0)

    label = f"{EMOJI_BLOCKED} blocked" if emoji == EMOJI_BLOCKED else f"{EMOJI_QUESTION} question"
    log(session_id, "attention", f"-> {label} ({clean_title!r})")
    set_attention_emoji(session_id, emoji, clean_title, timestamp, "attention")

    # PostToolUse:ExitPlanMode never fires in Claude Code, so mark planpending
    # here. session-end-hook.py reads this flag and skips the title reset,
    # preserving the current title across the plan acceptance session boundary.
    if event == "PermissionRequest" and data.get("tool_name") == "ExitPlanMode":
        new_title = f"{emoji} {clean_title}"
        write_debounce(session_id, timestamp, new_title, plan_state="planpending")
        log(session_id, "plan-accept", "marked planpending")

    sys.exit(0)


if __name__ == "__main__":
    main()
