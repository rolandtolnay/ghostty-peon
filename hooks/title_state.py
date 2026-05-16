"""Persistent Ghostty tab title state.

This module owns the debounce file contract shared by the hook scripts:

    line 1: timestamp
    line 2: raw title, including any leading status emoji
    line 3: optional plan state, currently "planpending"

The file format is intentionally unchanged; callers should use this module
instead of parsing or writing the files directly.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


PLAN_PENDING = "planpending"


def _namespace() -> str:
    value = os.environ.get("GHOSTTY_PEON_NAMESPACE", "claude").strip().lower()
    return value or "claude"


def _tmp_path(name: str) -> str:
    return f"/tmp/{_namespace()}-{name}"


def debounce_dir() -> str:
    return os.environ.get("GHOSTTY_PEON_DEBOUNCE_DIR", _tmp_path("tabtitle"))


@dataclass(frozen=True)
class TitleState:
    timestamp: str = "0"
    title: str = ""
    plan_state: str = ""

    @property
    def has_title(self) -> bool:
        return bool(self.title.strip())

    @property
    def is_plan_pending(self) -> bool:
        return self.plan_state == PLAN_PENDING


def debounce_path(session_id: str) -> str:
    return os.path.join(debounce_dir(), session_id)


def origin_path(session_id: str) -> str:
    return os.path.join(debounce_dir(), f"{session_id}.origin")


def exists(session_id: str) -> bool:
    return os.path.exists(debounce_path(session_id))


def read_lines(session_id: str) -> list[str]:
    try:
        with open(debounce_path(session_id)) as f:
            return f.read().strip().split("\n")
    except OSError:
        return []


def read(session_id: str) -> TitleState:
    lines = read_lines(session_id)
    timestamp = lines[0] if lines and lines[0] else "0"
    title = lines[1] if len(lines) >= 2 else ""
    plan_state = lines[2] if len(lines) >= 3 else ""
    return TitleState(timestamp=timestamp, title=title, plan_state=plan_state)


def write(session_id: str, timestamp: str, title: str, plan_state: str = "") -> None:
    os.makedirs(debounce_dir(), exist_ok=True)
    with open(debounce_path(session_id), "w") as f:
        f.write(f"{timestamp}\n{title}")
        if plan_state:
            f.write(f"\n{plan_state}")


def delete(session_id: str, include_origin: bool = True) -> None:
    suffixes = ("", ".origin") if include_origin else ("",)
    for suffix in suffixes:
        try:
            os.remove(os.path.join(debounce_dir(), f"{session_id}{suffix}"))
        except OSError:
            pass


def read_origin(session_id: str) -> str:
    try:
        with open(origin_path(session_id)) as f:
            return f.read()
    except OSError:
        return ""


def write_origin(session_id: str, message: str, max_chars: int | None = None) -> None:
    os.makedirs(debounce_dir(), exist_ok=True)
    text = message if max_chars is None else message[:max_chars]
    with open(origin_path(session_id), "w") as f:
        f.write(text)


def delete_origin(session_id: str) -> None:
    try:
        os.remove(origin_path(session_id))
    except OSError:
        pass
