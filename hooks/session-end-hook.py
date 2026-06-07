#!/usr/bin/env python3
"""Clean up session state on session end.

Claude treats SessionEnd as terminal teardown. Pi has richer replacement flows
(new/resume/fork/compact), so Pi keeps per-session title debounce state and only
uses terminal-scoped handoff where a replacement session should inherit the tab
label immediately.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lifecycle_policy
import title_state
import workflow_state
from sound_utils import (
    EMOJI_WORKING,
    get_terminal_id,
    log,
    release_terminal_id,
    release_unit,
    set_tab_title,
    skip_subagent_payload,
    strip_all_emojis,
    write_plan_handoff,
    write_replacement_handoff,
    _namespace,
)

data = json.load(sys.stdin)
session_id = data.get("session_id", "unknown")
if skip_subagent_payload(data, session_id, "session"):
    sys.exit(0)
cwd = data.get("cwd", "")
shutdown_reason = data.get("shutdown_reason", "")
target_session_file = data.get("target_session_file", "")


def read_debounce_lines() -> list[str]:
    return title_state.read_lines(session_id)


def current_clean_title(lines: list[str]) -> str:
    raw_title = lines[1] if len(lines) >= 2 else ""
    return strip_all_emojis(raw_title)


def replacement_handoff_title(raw_title: str, clean_title: str, shutdown_reason: str) -> str:
    if not clean_title:
        return ""
    if shutdown_reason in {"new", "resume"} and raw_title.strip():
        return raw_title.strip()
    return f"{EMOJI_WORKING} {clean_title}"


lines = read_debounce_lines()
clean_title = current_clean_title(lines)
term_id = get_terminal_id(session_id)
runtime = _namespace()
is_pi = lifecycle_policy.is_pi(runtime)

# Check debounce file for planpending flag before cleanup.
plan_accepted = lifecycle_policy.is_plan_pending(lines)
if plan_accepted:
    if clean_title:
        working_title = f"{EMOJI_WORKING} {clean_title}"
        if set_tab_title(working_title, session_id):
            log(session_id, "session", f"end -> plan accepted, title kept as {working_title!r}")
        else:
            log(session_id, "session", "end -> plan accepted, set_tab_title failed")
        if term_id and write_plan_handoff(term_id, working_title):
            log(session_id, "session", "end -> plan handoff written")
        elif term_id:
            log(session_id, "session", "end -> plan handoff write failed")
        else:
            log(session_id, "session", "end -> plan accepted but no terminal id for handoff")
    else:
        log(session_id, "session", "end -> plan accepted but no title to preserve")

# Pi replacement flows keep the visible title while the next session starts in
# the same tab. Normal quit is terminal teardown and should reset the title.
if lifecycle_policy.should_write_fork_handoff(runtime, shutdown_reason, plan_accepted, bool(clean_title), bool(term_id)):
    handoff_title = f"{EMOJI_WORKING} {clean_title}"
    if write_plan_handoff(term_id, handoff_title):
        log(session_id, "session", f"end -> fork handoff written {handoff_title!r}")
    else:
        log(session_id, "session", "end -> fork handoff write failed")

replacement_flow = lifecycle_policy.is_replacement_shutdown(runtime, shutdown_reason)
if replacement_flow:
    if term_id and target_session_file:
        raw_title = lines[1] if len(lines) >= 2 else ""
        handoff_title = replacement_handoff_title(raw_title, clean_title, shutdown_reason)
        if write_replacement_handoff(target_session_file, term_id, handoff_title):
            log(session_id, "session", f"end -> replacement handoff written for Pi {shutdown_reason}")
        else:
            log(session_id, "session", f"end -> replacement handoff write failed for Pi {shutdown_reason}")
    elif term_id:
        log(session_id, "session", f"end -> replacement handoff skipped: no target for Pi {shutdown_reason}")
    else:
        log(session_id, "session", f"end -> replacement handoff skipped: no terminal id for Pi {shutdown_reason}")
    log(session_id, "session", f"end -> preserved tab title for Pi {shutdown_reason}")
elif lifecycle_policy.should_reset_title_on_end(runtime, shutdown_reason, plan_accepted):
    # Reset tab title to directory name before releasing terminal ID.
    folder_name = os.path.basename(cwd) if cwd else ""
    if folder_name:
        if set_tab_title(folder_name, session_id):
            log(session_id, "session", f"end -> title reset to {folder_name!r}")
        else:
            log(session_id, "session", "end -> set_tab_title failed on reset")

# Keep debounce/origin only for Pi replacement flows. On normal quit, reset and
# clean up just like Claude so an inactive tab does not resurrect stale work.
if lifecycle_policy.should_keep_title_state_on_end(runtime, shutdown_reason):
    log(session_id, "session", f"end -> kept debounce state for Pi replacement (reason={shutdown_reason!r})")
else:
    if is_pi:
        workflow_state.deactivate(session_id=session_id, terminal_id=term_id or "")
        log(session_id, "session", f"end -> deactivated workflow bindings for Pi (reason={shutdown_reason!r})")
    title_state.delete(session_id)
    if is_pi:
        log(session_id, "session", f"end -> cleaned debounce state for Pi (reason={shutdown_reason!r})")

release_unit(session_id, cwd)
release_terminal_id(session_id)
log(session_id, "session", "end -> unit + terminal_id released")
