"""Terminal-scoped tab title handoff state.

Plan acceptance and Pi fork replacement flows use this short-lived handoff to
transfer the visible title from one session to the next session in the same
Ghostty terminal. The JSON shape is intentionally preserved:

    {"timestamp": <unix seconds>, "title": <string>}
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import runtime_config


def handoff_dir() -> str:
    return runtime_config.plan_handoff_dir()


def handoff_path(term_id: str) -> str:
    key = hashlib.sha256(term_id.encode("utf-8")).hexdigest()[:24]
    return os.path.join(handoff_dir(), key)


def replacement_session_key(session_file_or_id: str) -> str:
    """Return a stable key for a Pi replacement target session."""
    value = (session_file_or_id or "").strip()
    if not value:
        return ""
    name = Path(value).name
    stem = name[:-6] if name.endswith(".jsonl") else name
    return stem.rsplit("_", 1)[-1] if "_" in stem else stem


def replacement_handoff_path(session_file_or_id: str) -> str:
    key = replacement_session_key(session_file_or_id)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return os.path.join(handoff_dir(), f"replacement-{digest}")


def write(term_id: str, title: str) -> bool:
    """Persist a short-lived title handoff for a terminal."""
    try:
        os.makedirs(handoff_dir(), exist_ok=True)
        with open(handoff_path(term_id), "w") as f:
            json.dump({"timestamp": time.time(), "title": title}, f)
        return True
    except OSError:
        return False


def consume(term_id: str, ttl_seconds: int = 120) -> str | None:
    """Read and delete a fresh title handoff for a terminal, if one exists."""
    path = handoff_path(term_id)
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    title = data.get("title") if isinstance(data, dict) else None
    timestamp = data.get("timestamp") if isinstance(data, dict) else None
    if not isinstance(title, str) or not title.strip():
        return None
    if not isinstance(timestamp, (int, float)) or time.time() - float(timestamp) > ttl_seconds:
        return None
    return title.strip()


def write_replacement(target_session_file_or_id: str, term_id: str, title: str = "") -> bool:
    """Persist the terminal/title handoff for a Pi in-tab replacement target."""
    if not replacement_session_key(target_session_file_or_id) or not term_id:
        return False
    try:
        os.makedirs(handoff_dir(), exist_ok=True)
        with open(replacement_handoff_path(target_session_file_or_id), "w") as f:
            json.dump({"timestamp": time.time(), "terminal_id": term_id, "title": title}, f)
        return True
    except OSError:
        return False


def consume_replacement(session_id: str, session_file: str = "", ttl_seconds: int = 120) -> dict | None:
    """Read and delete a fresh Pi replacement handoff for this session."""
    keys = []
    for value in (session_file, session_id):
        key = replacement_session_key(value)
        if key and key not in keys:
            keys.append(key)

    for key in keys:
        path = replacement_handoff_path(key)
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

        if not isinstance(data, dict):
            continue
        timestamp = data.get("timestamp")
        term_id = data.get("terminal_id")
        title = data.get("title", "")
        if not isinstance(timestamp, (int, float)) or time.time() - float(timestamp) > ttl_seconds:
            continue
        if not isinstance(term_id, str) or not term_id.strip():
            continue
        if not isinstance(title, str):
            title = ""
        return {"terminal_id": term_id.strip(), "title": title.strip()}

    return None
