#!/usr/bin/env python3
"""Manage Ghostty tab attention state when Claude needs user input.

Open-time signals:
- PreToolUse:AskUserQuestion  -> EMOJI_QUESTION (before the dialog appears)
- PermissionRequest            -> EMOJI_BLOCKED (real tool permission block)
  Note: AskUserQuestion also fires PermissionRequest, but we skip it here
  since PreToolUse already handles it with the correct EMOJI_QUESTION.

Clear-time signals:
- PostToolUse:AskUserQuestion -> clear any attention emoji, restore EMOJI_WORKING
- PostToolUse:*               -> clear EMOJI_BLOCKED only (permission was accepted)

The emoji is also stripped by the UserPromptSubmit hook (tabtitle-hook.py)
when the user sends their next message.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sound_utils import (
    ALL_EMOJIS,
    DEBOUNCE_DIR,
    EMOJI_BLOCKED,
    EMOJI_QUESTION,
    EMOJI_WORKING,
    log,
    set_attention_emoji,
    set_status_emoji,
    set_tab_title,
    strip_all_emojis,
)


def get_debounce_path(session_id: str) -> str:
    return os.path.join(DEBOUNCE_DIR, f"{session_id}")


def read_debounce(session_id: str) -> tuple[str, str, str]:
    """Read timestamp, raw title, and plan state from debounce file.

    Plan state: '' (none), 'planpending' (set at PermissionRequest:ExitPlanMode,
    consumed by session-end-hook.py to skip title reset).
    """
    try:
        lines = open(get_debounce_path(session_id)).read().strip().split("\n")
        if len(lines) >= 2:
            plan_state = lines[2] if len(lines) >= 3 else ""
            return lines[0], lines[1], plan_state
    except OSError:
        pass
    return "0", "", ""


def write_debounce(session_id: str, timestamp: str, title: str, plan_state: str = "") -> None:
    debounce_path = get_debounce_path(session_id)
    try:
        os.makedirs(DEBOUNCE_DIR, exist_ok=True)
        with open(debounce_path, "w") as f:
            f.write(f"{timestamp}\n{title}")
            if plan_state:
                f.write(f"\n{plan_state}")
    except OSError:
        pass


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

    timestamp, raw_title, plan_state = read_debounce(session_id)
    clean_title = strip_emoji(raw_title)

    # Determine which action to take
    if event == "PreToolUse":
        tool = data.get("tool_name", "")
        if tool != "AskUserQuestion":
            log(session_id, "attention", f"skip: PreToolUse for non-target tool={tool!r}")
            sys.exit(0)
        log(session_id, "attention", f"PreToolUse:AskUserQuestion title={raw_title!r}")
        emoji = EMOJI_QUESTION
    elif event == "PermissionRequest":
        tool = data.get("tool_name", "")
        log(session_id, "attention", f"PermissionRequest:{tool} title={raw_title!r}")
        # AskUserQuestion fires both PreToolUse and PermissionRequest;
        # PreToolUse handles it with 💬, so skip here to avoid double sound
        if tool == "AskUserQuestion":
            log(session_id, "attention", "skip: AskUserQuestion handled by PreToolUse")
            sys.exit(0)
        emoji = EMOJI_BLOCKED
        # Don't override an existing attention emoji (🔥 or ⭐), but DO replace 🌊 (working)
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
        # AskUserQuestion clears any attention emoji (⭐ or 🔥)
        # Other tools only clear 🔥 (means permission was accepted)
        if tool != "AskUserQuestion" and not raw_title.startswith(f"{EMOJI_BLOCKED} "):
            log(session_id, "attention", f"skip: non-AskUserQuestion tool, emoji is not {EMOJI_BLOCKED}")
            sys.exit(0)
        if not clean_title:
            log(session_id, "attention", "skip: no established title to restore")
            sys.exit(0)
        # Restore 🌊 working emoji — Claude is still processing after permission accepted
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
