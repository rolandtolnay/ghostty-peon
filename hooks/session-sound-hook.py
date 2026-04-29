#!/usr/bin/env python3
"""Handle session lifecycle events for Ghostty tab hooks.

- startup: assign a unit to this session and play a Warcraft sound
- clear: delete the debounce file and re-assign unit (SessionEnd fires before
  SessionStart on /clear, releasing the old assignment)
- resume: assign unit if no existing assignment (migration safety)
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
    is_terminal_owned,
    log,
    play_sound,
    release_terminal_id,
    _get_session_unit,
)

data = json.load(sys.stdin)
source = data.get("source", "")
session_id = data.get("session_id", "unknown")
cwd = data.get("cwd", "")

if source == "startup":
    term_id = capture_terminal_id(session_id)
    log(session_id, "session", f"startup -> captured terminal_id={term_id!r}")
    # Detect subagent: if another session already owns this terminal,
    # skip all hooks to prevent duplicate sounds and tab title clobbering
    if term_id:
        owner = is_terminal_owned(term_id, session_id)
        if owner:
            release_terminal_id(session_id)
            log(session_id, "session", f"startup -> subagent detected (terminal owned by {owner}), skipping all hooks")
            sys.exit(0)
    unit = assign_unit(session_id, cwd)
    log(session_id, "session", f"startup -> assigned unit={unit!r}")
    if unit:
        play_sound("session.start", session_id)
elif source == "clear":
    debounce_path = os.path.join(DEBOUNCE_DIR, session_id)
    try:
        os.remove(debounce_path)
        log(session_id, "session", "clear -> debounce file deleted")
    except OSError:
        log(session_id, "session", "clear -> no debounce file to delete")
    term_id = capture_terminal_id(session_id)
    log(session_id, "session", f"clear -> re-captured terminal_id={term_id!r}")
    unit = assign_unit(session_id, cwd)
    log(session_id, "session", f"clear -> re-assigned unit={unit!r}")
    if unit:
        play_sound("session.start", session_id)
elif source == "resume":
    term_id = capture_terminal_id(session_id)
    log(session_id, "session", f"resume -> captured terminal_id={term_id!r}")
    existing = _get_session_unit(session_id)
    if not existing:
        unit = assign_unit(session_id, cwd)
        log(session_id, "session", f"resume -> assigned unit={unit!r} (migration)")
    else:
        log(session_id, "session", f"resume -> existing unit={existing[1]!r}")
else:
    log(session_id, "session", f"source={source!r} (no action)")
