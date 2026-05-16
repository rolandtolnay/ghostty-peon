"""Ghostty terminal targeting and tab-title mutation.

This module owns the terminal-scoped safety invariant for tab title changes:
when a session id is provided, title mutation is allowed only if that session
has a captured Ghostty terminal id. Otherwise it refuses the unsafe fallback.
"""

from __future__ import annotations

from collections.abc import Callable
import os
import subprocess


LogFn = Callable[[str, str, str], None]


def _namespace() -> str:
    value = os.environ.get("GHOSTTY_PEON_NAMESPACE", "claude").strip().lower()
    return value or "claude"


def _tmp_path(name: str) -> str:
    return f"/tmp/{_namespace()}-{name}"


def terminal_id_dir() -> str:
    return os.environ.get("GHOSTTY_PEON_TERMINAL_ID_DIR", _tmp_path("tabterminal"))


def terminal_id_path(session_id: str) -> str:
    return os.path.join(terminal_id_dir(), session_id)


def capture_terminal_id(session_id: str) -> str | None:
    """Capture and persist the Ghostty terminal UUID for the focused tab."""
    try:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "Ghostty"\n'
                "    set t to focused terminal of selected tab of front window\n"
                "    return id of t\n"
                "end tell",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        term_id = result.stdout.strip()
        if not term_id:
            return None
        os.makedirs(terminal_id_dir(), exist_ok=True)
        with open(terminal_id_path(session_id), "w") as f:
            f.write(term_id)
        return term_id
    except Exception:
        return None


def is_terminal_owned(term_id: str, exclude_session: str) -> str | None:
    """Return another session id that owns this terminal, if any."""
    try:
        for name in os.listdir(terminal_id_dir()):
            if name == exclude_session:
                continue
            try:
                with open(terminal_id_path(name)) as f:
                    existing = f.read().strip()
                if existing == term_id:
                    return name
            except OSError:
                continue
    except OSError:
        pass
    return None


def clear_terminal_owner(term_id: str, exclude_session: str) -> str | None:
    """Remove another session's ownership of this terminal and return it."""
    owner = is_terminal_owned(term_id, exclude_session)
    if not owner:
        return None
    try:
        os.remove(terminal_id_path(owner))
    except OSError:
        pass
    return owner


def get_terminal_id(session_id: str) -> str | None:
    """Read the persisted Ghostty terminal UUID for a session."""
    try:
        with open(terminal_id_path(session_id)) as f:
            return f.read().strip() or None
    except OSError:
        return None


def release_terminal_id(session_id: str) -> None:
    """Delete the persisted terminal id for a session. Silent on failure."""
    try:
        os.remove(terminal_id_path(session_id))
    except OSError:
        pass


def set_tab_title(title: str, session_id: str | None = None, log_fn: LogFn | None = None) -> bool:
    """Set a Ghostty tab title.

    If session_id is provided, use the captured terminal id and refuse unsafe
    fallback when no id exists. Without session_id, retain the legacy focused-tab
    fallback used by manual callers.
    """
    term_id = get_terminal_id(session_id) if session_id else None
    if session_id:
        if term_id:
            if log_fn:
                log_fn(session_id, "tabtitle", f"target: term_id={term_id!r}")
        else:
            if log_fn:
                log_fn(session_id, "tabtitle", "target: SKIPPED (no term_id, refusing unsafe fallback)")
            return False
    if term_id:
        script = (
            'tell application "Ghostty"\n'
            f'    perform action "set_tab_title:{title}" on '
            f'(first terminal whose id is "{term_id}")\n'
            "end tell"
        )
    else:
        script = (
            'tell application "Ghostty"\n'
            "    set t to focused terminal of selected tab of front window\n"
            f'    perform action "set_tab_title:{title}" on t\n'
            "end tell"
        )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0 and session_id and log_fn:
            stderr = result.stderr.strip() if isinstance(result.stderr, str) else (result.stderr or b"").decode().strip()
            log_fn(session_id, "tabtitle", f"osascript failed: rc={result.returncode} stderr={stderr!r}")
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError) as e:
        if session_id and log_fn:
            log_fn(session_id, "tabtitle", f"osascript exception: {e}")
        return False


def is_tab_focused(session_id: str) -> bool:
    """Return True iff Ghostty is frontmost and this session's terminal is focused."""
    term_id = get_terminal_id(session_id) if session_id else None
    if not term_id:
        return False
    try:
        script = (
            'tell application "System Events"\n'
            '    set frontApp to name of first application process whose frontmost is true\n'
            'end tell\n'
            'if frontApp is not "Ghostty" then return "NOT_FRONTMOST"\n'
            'tell application "Ghostty"\n'
            '    set t to focused terminal of selected tab of front window\n'
            '    return id of t\n'
            'end tell'
        )
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False
        return result.stdout.strip() == term_id
    except Exception:
        return False
