#!/usr/bin/env python3
"""Handle session lifecycle events for Ghostty tab hooks.

Pi is treated as the primary lifecycle model:
- startup/new/fork: capture the Ghostty terminal, assign a unit, play start sound
- resume: capture terminal, restore existing title state, assign unit if needed
- compact: re-capture terminal and restore the existing title after compaction
- clear: legacy Claude-style clear support
"""

import json
import os
import sys

# Guard against recursive execution from claude -p subprocesses
if os.environ.get("_CLAUDE_HOOK_NESTED"):
    sys.exit(0)

# Allow callers to suppress sounds (e.g. ccommit alias)
if os.environ.get("_CLAUDE_NO_SOUND"):
    sys.exit(0)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sound_utils import (
    DEBOUNCE_DIR,
    assign_unit,
    capture_terminal_id,
    clear_terminal_owner,
    consume_plan_handoff,
    is_terminal_owned,
    log,
    play_sound,
    release_terminal_id,
    set_tab_title,
    _get_session_unit,
    _namespace,
)

data = json.load(sys.stdin)
source = data.get("source", "")
session_id = data.get("session_id", "unknown")
cwd = data.get("cwd", "")
pi_reason = data.get("pi_reason", source)
session_file = data.get("session_file", "")
previous_session_file = data.get("previous_session_file", "")


def _short_path(path: str) -> str:
    if not path:
        return ""
    return os.path.basename(path)


def apply_title_handoff(term_id: str | None) -> bool:
    """Seed the new session after a terminal-scoped title handoff."""
    if not term_id:
        return False
    title = consume_plan_handoff(term_id)
    if not title:
        return False
    try:
        os.makedirs(DEBOUNCE_DIR, exist_ok=True)
        with open(os.path.join(DEBOUNCE_DIR, session_id), "w") as f:
            # Timestamp 0 lets the first prompt after fork/plan handoff re-evaluate
            # immediately instead of being blocked by the normal rename cooldown.
            f.write(f"0\n{title}")
    except OSError as e:
        log(session_id, "session", f"handoff debounce write failed: {e}")
        return False
    if set_tab_title(title, session_id):
        log(session_id, "session", f"handoff restored title {title!r}")
        return True
    log(session_id, "session", "handoff set_tab_title failed")
    return False


def restore_existing_title() -> bool:
    """Restore this session's persisted title, if one exists."""
    try:
        lines = open(os.path.join(DEBOUNCE_DIR, session_id)).read().strip().split("\n")
    except OSError:
        return False
    title = lines[1].strip() if len(lines) >= 2 else ""
    if not title:
        return False
    if set_tab_title(title, session_id):
        log(session_id, "session", f"restored existing title {title!r}")
        return True
    log(session_id, "session", "restore existing title failed")
    return False


def reset_to_folder(label: str) -> bool:
    folder_name = os.path.basename(cwd) if cwd else ""
    if not folder_name:
        return False
    if set_tab_title(folder_name, session_id):
        log(session_id, "session", f"{label} -> title reset to {folder_name!r}")
        return True
    log(session_id, "session", f"{label} -> set_tab_title failed on reset")
    return False


def capture_and_claim(label: str, replace_existing_owner: bool = False) -> str | None:
    term_id = capture_terminal_id(session_id)
    log(
        session_id,
        "session",
        f"{label} -> captured terminal_id={term_id!r} "
        f"(reason={pi_reason!r}, file={_short_path(session_file)!r}, prev={_short_path(previous_session_file)!r})",
    )
    if not term_id:
        return None

    owner = is_terminal_owned(term_id, session_id)
    if not owner:
        return term_id

    if _namespace() == "pi" and replace_existing_owner:
        replaced = clear_terminal_owner(term_id, session_id)
        log(session_id, "session", f"{label} -> replaced terminal owner {replaced!r}")
        return term_id

    # Plain startup keeps the nested-session protection to avoid stealing a
    # parent Pi/Claude session's terminal ownership.
    release_terminal_id(session_id)
    log(session_id, "session", f"{label} -> subagent detected (terminal owned by {owner}), skipping all hooks")
    sys.exit(0)


if source in {"startup", "new", "fork"}:
    term_id = capture_and_claim(source, replace_existing_owner=source in {"new", "fork"})
    unit = assign_unit(session_id, cwd)
    log(session_id, "session", f"{source} -> assigned unit={unit!r}")
    if not apply_title_handoff(term_id):
        # Helpful for process restarts where the same persisted Pi session starts again.
        restore_existing_title()
    if unit:
        play_sound("session.start", session_id)
elif source == "clear":
    debounce_path = os.path.join(DEBOUNCE_DIR, session_id)
    try:
        os.remove(debounce_path)
        log(session_id, "session", "clear -> debounce file deleted")
    except OSError:
        log(session_id, "session", "clear -> no debounce file to delete")
    term_id = capture_and_claim("clear")
    unit = assign_unit(session_id, cwd)
    log(session_id, "session", f"clear -> re-assigned unit={unit!r}")
    apply_title_handoff(term_id)
    if unit:
        play_sound("session.start", session_id)
elif source == "resume":
    term_id = capture_and_claim("resume", replace_existing_owner=True)
    if not apply_title_handoff(term_id) and not restore_existing_title():
        reset_to_folder("resume")
    existing = _get_session_unit(session_id)
    if not existing:
        unit = assign_unit(session_id, cwd)
        log(session_id, "session", f"resume -> assigned unit={unit!r} (migration)")
    else:
        log(session_id, "session", f"resume -> existing unit={existing[1]!r}")
elif source == "compact":
    capture_and_claim("compact", replace_existing_owner=True)
    if not restore_existing_title():
        log(session_id, "session", "compact -> no existing title to restore")
else:
    log(session_id, "session", f"source={source!r} (no action)")
