#!/usr/bin/env python3
"""Clean up session state on session end.

- Release unit assignment
- Reset Ghostty tab title to the working directory name (unless plan was just accepted)
- Release terminal ID
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sound_utils import log, release_terminal_id, release_unit, set_tab_title, strip_all_emojis

data = json.load(sys.stdin)
session_id = data.get("session_id", "unknown")
cwd = data.get("cwd", "")

# Check debounce file for planpending flag before cleanup deletes it.
# If a plan was just accepted, preserve the current title instead of
# resetting to the folder name — the new session will generate a fresh
# title (with sound) on the first user message.
debounce_dir = "/tmp/claude-tabtitle"
debounce_path = os.path.join(debounce_dir, session_id)
plan_accepted = False
try:
    lines = open(debounce_path).read().strip().split("\n")
    if len(lines) >= 3 and lines[2] == "planpending":
        plan_accepted = True
        raw_title = lines[1] if len(lines) >= 2 else ""
        clean_title = strip_all_emojis(raw_title)
        if clean_title:
            if set_tab_title(clean_title, session_id):
                log(session_id, "session", f"end -> plan accepted, title kept as {clean_title!r}")
            else:
                log(session_id, "session", "end -> plan accepted, set_tab_title failed")
        else:
            log(session_id, "session", "end -> plan accepted but no title to preserve")
except OSError:
    pass

if not plan_accepted:
    # Reset tab title to directory name before releasing terminal ID
    folder_name = os.path.basename(cwd) if cwd else ""
    if folder_name:
        if set_tab_title(folder_name, session_id):
            log(session_id, "session", f"end -> title reset to {folder_name!r}")
        else:
            log(session_id, "session", "end -> set_tab_title failed on reset")

# Clean up debounce and origin files
for suffix in ("", ".origin"):
    try:
        os.remove(os.path.join(debounce_dir, f"{session_id}{suffix}"))
    except OSError:
        pass

release_unit(session_id, cwd)
release_terminal_id(session_id)
log(session_id, "session", "end -> cleaned up debounce, unit + terminal_id released")
