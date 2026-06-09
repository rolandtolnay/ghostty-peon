"""Ghostty terminal targeting and tab-title mutation.

This module owns the terminal-scoped safety invariant for tab title changes:
when a session id is provided, title mutation is allowed only if that session
has a captured Ghostty terminal id. Otherwise it refuses the unsafe fallback.
"""

from __future__ import annotations

from collections.abc import Callable
import os
import subprocess

import runtime_config


LogFn = Callable[[str, str, str], None]


def terminal_id_dir() -> str:
    return runtime_config.terminal_id_dir()


def terminal_id_path(session_id: str) -> str:
    return os.path.join(terminal_id_dir(), session_id)


def _default_terminal_id_dir(namespace: str) -> str:
    return f"/tmp/{namespace}-tabterminal"


def _peer_terminal_id_dirs() -> list[str]:
    """Return peer runtime terminal-id dirs that may already own a tab.

    Claude and Pi keep separate state namespaces, but Ghostty terminal UUIDs are
    global. A tab captured by one runtime must therefore block plain startup
    capture by the other runtime too.
    """
    configured = os.environ.get("GHOSTTY_PEON_PEER_TERMINAL_ID_DIRS", "").strip()
    if configured:
        return [path for path in configured.split(os.pathsep) if path]

    current = runtime_config.namespace()
    current_dir = os.path.abspath(terminal_id_dir())
    default_current_dir = os.path.abspath(_default_terminal_id_dir(current))

    # Isolated tests and explicit embedders often override the current terminal
    # dir; require them to opt into peer dirs so they do not accidentally read
    # or mutate real /tmp state. Production adapters may still set the default
    # path explicitly, which should keep cross-runtime ownership checks enabled.
    if "GHOSTTY_PEON_TERMINAL_ID_DIR" in os.environ and current_dir != default_current_dir:
        return []

    return [_default_terminal_id_dir(namespace) for namespace in ("claude", "pi") if namespace != current]


def _terminal_owner_dirs() -> list[str]:
    seen: set[str] = set()
    dirs: list[str] = []
    for directory in [terminal_id_dir(), *_peer_terminal_id_dirs()]:
        normalized = os.path.abspath(directory)
        if normalized in seen:
            continue
        seen.add(normalized)
        dirs.append(directory)
    return dirs


def _namespace_label(directory: str) -> str:
    normalized = os.path.abspath(directory)
    current_dir = os.path.abspath(terminal_id_dir())
    if normalized == current_dir:
        return runtime_config.namespace()
    for namespace in ("claude", "pi"):
        if normalized == os.path.abspath(_default_terminal_id_dir(namespace)):
            return namespace
    basename = os.path.basename(normalized).lower()
    for namespace in ("claude", "pi"):
        if basename.startswith(namespace):
            return namespace
    return "peer"


def _owner_display(directory: str, session_id: str) -> str:
    if os.path.abspath(directory) == os.path.abspath(terminal_id_dir()):
        return session_id
    return f"{_namespace_label(directory)}:{session_id}"


def _find_terminal_owner(term_id: str, exclude_session: str) -> tuple[str, str, str] | None:
    """Return (directory, session_id, display) for another owner of term_id."""
    current_dir = os.path.abspath(terminal_id_dir())
    for directory in _terminal_owner_dirs():
        directory_abs = os.path.abspath(directory)
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            if directory_abs == current_dir and name == exclude_session:
                continue
            try:
                with open(os.path.join(directory, name)) as f:
                    existing = f.read().strip()
                if existing == term_id:
                    return directory, name, _owner_display(directory, name)
            except OSError:
                continue
    return None


def save_terminal_id(session_id: str, term_id: str) -> None:
    """Persist a known Ghostty terminal UUID for a session."""
    os.makedirs(terminal_id_dir(), exist_ok=True)
    with open(terminal_id_path(session_id), "w") as f:
        f.write(term_id)


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
        save_terminal_id(session_id, term_id)
        return term_id
    except Exception:
        return None


def is_terminal_owned(term_id: str, exclude_session: str) -> str | None:
    """Return another session id that owns this terminal, if any.

    Ownership is checked across Claude/Pi terminal-id namespaces because
    Ghostty terminal UUIDs are global even when hook state is runtime-scoped.
    Peer-runtime owners are returned as ``"namespace:session_id"``.
    """
    owner = _find_terminal_owner(term_id, exclude_session)
    return owner[2] if owner else None


def clear_terminal_owner(term_id: str, exclude_session: str) -> str | None:
    """Remove a same-runtime owner of this terminal and return it.

    Peer runtime ownership is a guardrail, not a replacement target: a Pi
    replacement flow must not delete Claude's terminal ownership, and vice versa.
    """
    current_dir = terminal_id_dir()
    try:
        for name in os.listdir(current_dir):
            if name == exclude_session:
                continue
            try:
                path = os.path.join(current_dir, name)
                with open(path) as f:
                    existing = f.read().strip()
                if existing != term_id:
                    continue
                try:
                    os.remove(path)
                except OSError:
                    pass
                return name
            except OSError:
                continue
    except OSError:
        pass
    return None


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


def _stderr_text(stderr: str | bytes | None) -> str:
    if isinstance(stderr, str):
        return stderr.strip()
    return (stderr or b"").decode(errors="replace").strip()


def _is_stale_terminal_error(stderr: str, term_id: str) -> bool:
    """Return True for Ghostty object-not-found errors for our terminal id."""
    if not term_id or term_id not in stderr or "terminal" not in stderr.lower():
        return False
    return "-1728" in stderr or "Can't get" in stderr or "Can’t get" in stderr


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
        if result.returncode != 0 and session_id:
            stderr = _stderr_text(result.stderr)
            if log_fn:
                log_fn(session_id, "tabtitle", f"osascript failed: rc={result.returncode} stderr={stderr!r}")
            if term_id and _is_stale_terminal_error(stderr, term_id):
                release_terminal_id(session_id)
                if log_fn:
                    log_fn(session_id, "tabtitle", f"stale terminal id released: {term_id!r}")
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
