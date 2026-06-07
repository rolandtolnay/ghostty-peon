"""Durable Pi Canonical Workflow Mode state.

State is scoped to Workstreams, not projects or branches. The public facade keeps
callers away from the JSON mechanics so the on-disk shape can evolve without
changing hook behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import time
import uuid

import runtime_config
import workflow_model


@dataclass(frozen=True)
class Workstream:
    id: str
    state: str
    slug: str
    last_title: str = ""
    cwd: str = ""
    branch: str = ""
    artifacts: tuple[str, ...] = ()
    active_sessions: tuple[str, ...] = ()
    active_terminals: tuple[str, ...] = ()


def state_file() -> str:
    return runtime_config.workflow_state_file()


def attach(
    session_id: str = "",
    terminal_id: str = "",
    state: str = "",
    slug: str = "",
    cwd: str = "",
    branch: str = "",
    artifacts: tuple[str, ...] | list[str] = (),
    title: str = "",
) -> Workstream:
    """Attach the current session/tab/artifacts to a Workstream and persist it."""
    data = _load()
    workstreams = data.setdefault("workstreams", {})
    artifact_paths = _clean_artifacts(artifacts)
    wid = _find_workstream_id(data, session_id=session_id, terminal_id=terminal_id, artifacts=artifact_paths)
    now = time.time()

    if wid and wid in workstreams:
        record = workstreams[wid]
    else:
        wid = _new_id()
        record = {
            "id": wid,
            "state": "",
            "slug": "",
            "last_title": "",
            "cwd": "",
            "branch": "",
            "artifacts": [],
            "active_sessions": [],
            "active_terminals": [],
            "created_at": now,
            "updated_at": now,
        }
        workstreams[wid] = record

    normalized_state = _normalize_state(state) or record.get("state", "")
    normalized_slug = workflow_model.normalize_slug(slug) or record.get("slug", "")
    if normalized_state:
        record["state"] = normalized_state
    if normalized_slug:
        record["slug"] = normalized_slug
    if title:
        record["last_title"] = title
    elif normalized_state and normalized_slug:
        record["last_title"] = f"{normalized_state}-{normalized_slug}"
    if cwd:
        record["cwd"] = cwd
    if branch:
        record["branch"] = branch
    _append_unique(record.setdefault("active_sessions", []), session_id)
    _append_unique(record.setdefault("active_terminals", []), terminal_id)
    for artifact in artifact_paths:
        _append_unique(record.setdefault("artifacts", []), artifact)
    record["updated_at"] = now

    _save(data)
    return _to_workstream(record)


def resolve(
    session_id: str = "",
    terminal_id: str = "",
    artifacts: tuple[str, ...] | list[str] = (),
) -> Workstream | None:
    """Resolve only active session/tab bindings or explicit artifact attachments."""
    data = _load()
    wid = _find_workstream_id(
        data,
        session_id=session_id,
        terminal_id=terminal_id,
        artifacts=_clean_artifacts(artifacts),
    )
    if not wid:
        return None
    record = data.get("workstreams", {}).get(wid)
    return _to_workstream(record) if isinstance(record, dict) else None


def deactivate(session_id: str = "", terminal_id: str = "") -> None:
    """Deactivate active session/tab bindings while preserving Workstream artifacts."""
    if not session_id and not terminal_id:
        return
    data = _load()
    changed = False
    for record in data.get("workstreams", {}).values():
        if not isinstance(record, dict):
            continue
        record_changed = False
        if session_id and _remove_value(record.setdefault("active_sessions", []), session_id):
            record_changed = True
        if terminal_id and _remove_value(record.setdefault("active_terminals", []), terminal_id):
            record_changed = True
        if record_changed:
            record["updated_at"] = time.time()
            changed = True
    if changed:
        _save(data)


def transfer_binding(old_session_id: str = "", new_session_id: str = "", terminal_id: str = "") -> Workstream | None:
    """Transfer an active Workstream binding to a replacement Pi session."""
    if not new_session_id:
        return None
    data = _load()
    wid = _find_workstream_id(data, session_id=old_session_id, terminal_id=terminal_id)
    if not wid:
        return None
    record = data.get("workstreams", {}).get(wid)
    if not isinstance(record, dict):
        return None
    if old_session_id:
        _remove_value(record.setdefault("active_sessions", []), old_session_id)
    _append_unique(record.setdefault("active_sessions", []), new_session_id)
    _append_unique(record.setdefault("active_terminals", []), terminal_id)
    record["updated_at"] = time.time()
    _save(data)
    return _to_workstream(record)


def _find_workstream_id(
    data: dict,
    session_id: str = "",
    terminal_id: str = "",
    artifacts: tuple[str, ...] | list[str] = (),
) -> str:
    workstreams = data.get("workstreams", {})
    if not isinstance(workstreams, dict):
        return ""

    for wid, record in workstreams.items():
        if not isinstance(record, dict):
            continue
        if session_id and session_id in record.get("active_sessions", []):
            return wid
        if terminal_id and terminal_id in record.get("active_terminals", []):
            return wid

    artifact_set = set(_clean_artifacts(artifacts))
    if artifact_set:
        for wid, record in workstreams.items():
            if not isinstance(record, dict):
                continue
            if artifact_set.intersection(record.get("artifacts", [])):
                return wid
    return ""


def _load() -> dict:
    try:
        with open(state_file()) as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("version") == 1 and isinstance(data.get("workstreams"), dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"version": 1, "workstreams": {}}


def _save(data: dict) -> None:
    path = state_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _to_workstream(record: dict) -> Workstream:
    return Workstream(
        id=str(record.get("id", "")),
        state=str(record.get("state", "")),
        slug=str(record.get("slug", "")),
        last_title=str(record.get("last_title", "")),
        cwd=str(record.get("cwd", "")),
        branch=str(record.get("branch", "")),
        artifacts=tuple(value for value in record.get("artifacts", []) if isinstance(value, str)),
        active_sessions=tuple(value for value in record.get("active_sessions", []) if isinstance(value, str)),
        active_terminals=tuple(value for value in record.get("active_terminals", []) if isinstance(value, str)),
    )


def _new_id() -> str:
    return f"ws-{uuid.uuid4().hex[:16]}"


def _normalize_state(state: str) -> str:
    value = state.strip().lower() if isinstance(state, str) else ""
    return value if value in workflow_model.WORKFLOW_STATES else ""


def _clean_artifacts(artifacts: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    cleaned = []
    seen = set()
    for value in artifacts or ():
        if not isinstance(value, str):
            continue
        path = value.strip()
        if not path or path in seen:
            continue
        seen.add(path)
        cleaned.append(path)
    return tuple(cleaned)


def _append_unique(values: list, value: str) -> None:
    if value and value not in values:
        values.append(value)


def _remove_value(values: list, value: str) -> bool:
    if value not in values:
        return False
    values[:] = [item for item in values if item != value]
    return True
