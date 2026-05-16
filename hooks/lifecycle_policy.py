"""Runtime lifecycle policy for Ghostty Peon hooks.

This module answers lifecycle questions without touching files, Ghostty, sounds,
or subprocesses. Hook scripts remain adapters that perform the side effects.
"""

from __future__ import annotations


PLAN_PENDING = "planpending"
PI_REPLACEMENT_SHUTDOWNS = frozenset({"fork", "resume", "new"})
PI_OWNER_REPLACING_STARTS = frozenset({"new", "fork", "resume", "compact"})


def is_pi(runtime: str) -> bool:
    return runtime == "pi"


def start_replaces_terminal_owner(runtime: str, source: str) -> bool:
    """Whether SessionStart may replace an existing terminal owner."""
    return is_pi(runtime) and source in PI_OWNER_REPLACING_STARTS


def is_plan_pending(lines: list[str]) -> bool:
    """Whether debounce lines represent an accepted plan transition."""
    return len(lines) >= 3 and lines[2] == PLAN_PENDING


def is_replacement_shutdown(runtime: str, shutdown_reason: str) -> bool:
    """Whether shutdown is part of a Pi in-tab replacement flow."""
    return is_pi(runtime) and shutdown_reason in PI_REPLACEMENT_SHUTDOWNS


def should_write_fork_handoff(
    runtime: str,
    shutdown_reason: str,
    plan_accepted: bool,
    has_clean_title: bool,
    has_terminal_id: bool,
) -> bool:
    """Whether Pi fork shutdown should hand off the visible working title."""
    return (
        is_pi(runtime)
        and shutdown_reason == "fork"
        and not plan_accepted
        and has_clean_title
        and has_terminal_id
    )


def should_reset_title_on_end(runtime: str, shutdown_reason: str, plan_accepted: bool) -> bool:
    """Whether SessionEnd should reset the tab title to the folder name."""
    return not is_replacement_shutdown(runtime, shutdown_reason) and not plan_accepted


def should_keep_title_state_on_end(runtime: str, shutdown_reason: str) -> bool:
    """Whether debounce/origin state should survive SessionEnd."""
    return is_replacement_shutdown(runtime, shutdown_reason)
