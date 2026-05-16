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

import runtime_config


def handoff_dir() -> str:
    return runtime_config.plan_handoff_dir()


def handoff_path(term_id: str) -> str:
    key = hashlib.sha256(term_id.encode("utf-8")).hexdigest()[:24]
    return os.path.join(handoff_dir(), key)


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
