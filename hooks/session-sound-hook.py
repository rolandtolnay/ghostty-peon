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
import lifecycle_policy
import title_state
from sound_utils import (
    assign_unit,
    capture_terminal_id,
    clear_terminal_owner,
    consume_plan_handoff,
    consume_replacement_handoff,
    is_terminal_owned,
    log,
    play_sound,
    release_terminal_id,
    save_terminal_id,
    set_tab_title,
    skip_subagent_payload,
    write_nested_hook_guard_env,
    _get_session_unit,
    _namespace,
)

data = json.load(sys.stdin)
source = data.get("source", "")
session_id = data.get("session_id", "unknown")
if skip_subagent_payload(data, session_id, "session"):
    sys.exit(0)
write_nested_hook_guard_env(session_id)
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
        # Timestamp 0 lets the first prompt after fork/plan handoff re-evaluate
        # immediately instead of being blocked by the normal rename cooldown.
        title_state.write(session_id, "0", title)
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
    title = title_state.read(session_id).title.strip()
    if not title:
        return False
    if set_tab_title(title, session_id):
        log(session_id, "session", f"restored existing title {title!r}")
        return True
    log(session_id, "session", "restore existing title failed")
    return False


def restore_replacement_handoff(label: str) -> str | None:
    """Claim the outgoing Pi terminal for an in-tab replacement session."""
    handoff = consume_replacement_handoff(session_id, session_file)
    if not handoff:
        return None
    term_id = handoff.get("terminal_id", "")
    if not term_id:
        return None
    try:
        save_terminal_id(session_id, term_id)
    except OSError as e:
        log(session_id, "session", f"{label} -> replacement terminal_id write failed: {e}")
        return None

    replaced = clear_terminal_owner(term_id, session_id)
    if replaced:
        log(session_id, "session", f"{label} -> replaced terminal owner {replaced!r}")
    log(session_id, "session", f"{label} -> restored replacement terminal_id={term_id!r}")

    title = handoff.get("title", "")
    if title:
        try:
            title_state.write(session_id, "0", title)
        except OSError as e:
            log(session_id, "session", f"{label} -> replacement debounce write failed: {e}")
        if set_tab_title(title, session_id):
            log(session_id, "session", f"{label} -> restored replacement title {title!r}")
        else:
            log(session_id, "session", f"{label} -> replacement set_tab_title failed")
    return term_id


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


runtime = _namespace()

if source in {"startup", "new", "fork"}:
    term_id = None
    if lifecycle_policy.start_replaces_terminal_owner(runtime, source):
        term_id = restore_replacement_handoff(source)
    if not term_id:
        term_id = capture_and_claim(source, replace_existing_owner=lifecycle_policy.start_replaces_terminal_owner(runtime, source))
    unit = assign_unit(session_id, cwd)
    log(session_id, "session", f"{source} -> assigned unit={unit!r}")
    if not apply_title_handoff(term_id):
        # Helpful for process restarts where the same persisted Pi session starts again.
        restore_existing_title()
    if unit:
        play_sound("session.start", session_id)
elif source == "clear":
    had_debounce = title_state.exists(session_id)
    title_state.delete(session_id, include_origin=False)
    if had_debounce:
        log(session_id, "session", "clear -> debounce file deleted")
    else:
        log(session_id, "session", "clear -> no debounce file to delete")
    term_id = capture_and_claim("clear")
    unit = assign_unit(session_id, cwd)
    log(session_id, "session", f"clear -> re-assigned unit={unit!r}")
    apply_title_handoff(term_id)
    if unit:
        play_sound("session.start", session_id)
elif source == "resume":
    term_id = restore_replacement_handoff("resume")
    if not term_id:
        term_id = capture_and_claim("resume", replace_existing_owner=lifecycle_policy.start_replaces_terminal_owner(runtime, source))
    if not apply_title_handoff(term_id) and not restore_existing_title():
        reset_to_folder("resume")
    existing = _get_session_unit(session_id)
    if not existing:
        unit = assign_unit(session_id, cwd)
        log(session_id, "session", f"resume -> assigned unit={unit!r} (migration)")
    else:
        log(session_id, "session", f"resume -> existing unit={existing[1]!r}")
elif source == "compact":
    capture_and_claim("compact", replace_existing_owner=lifecycle_policy.start_replaces_terminal_owner(runtime, source))
    if not restore_existing_title():
        log(session_id, "session", "compact -> no existing title to restore")
else:
    log(session_id, "session", f"source={source!r} (no action)")
