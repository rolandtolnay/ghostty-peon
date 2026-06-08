"""Durable Pi Canonical Workflow Mode state.

State is scoped to Workstreams, not projects or branches. The public functions
name whether a caller is resolving active tab/session ownership, explicit
artifact attachment, or replacement between Workstreams.
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


def create_workstream(
    session_id: str = "",
    terminal_id: str = "",
    state: str = "",
    slug: str = "",
    cwd: str = "",
    branch: str = "",
    artifacts: tuple[str, ...] | list[str] = (),
    title: str = "",
) -> Workstream:
    """Create a new Workstream and make the supplied session/tab active on it."""
    return _save_workstream(
        _load(),
        _new_id(),
        session_id=session_id,
        terminal_id=terminal_id,
        state=state,
        slug=slug,
        cwd=cwd,
        branch=branch,
        artifacts=_clean_artifacts(artifacts),
        title=title,
    )


def create_replacing_active_workstream(
    session_id: str = "",
    terminal_id: str = "",
    state: str = "",
    slug: str = "",
    cwd: str = "",
    branch: str = "",
    artifacts: tuple[str, ...] | list[str] = (),
    title: str = "",
) -> Workstream:
    """Create a new Workstream after removing this session/tab from active Workstreams."""
    data = _load()
    _remove_active_bindings(data, session_id=session_id, terminal_id=terminal_id)
    return _save_workstream(
        data,
        _new_id(),
        session_id=session_id,
        terminal_id=terminal_id,
        state=state,
        slug=slug,
        cwd=cwd,
        branch=branch,
        artifacts=_clean_artifacts(artifacts),
        title=title,
    )


def attach_to_existing_workstream(
    workstream_id: str,
    session_id: str = "",
    terminal_id: str = "",
    state: str = "",
    slug: str = "",
    cwd: str = "",
    branch: str = "",
    artifacts: tuple[str, ...] | list[str] = (),
    title: str = "",
) -> Workstream | None:
    """Attach the supplied session/tab to an explicit existing Workstream."""
    if not workstream_id:
        return None
    data = _load()
    if workstream_id not in data.get("workstreams", {}):
        return None
    return _save_workstream(
        data,
        workstream_id,
        session_id=session_id,
        terminal_id=terminal_id,
        state=state,
        slug=slug,
        cwd=cwd,
        branch=branch,
        artifacts=_clean_artifacts(artifacts),
        title=title,
    )


def replace_active_workstream(
    workstream_id: str,
    session_id: str = "",
    terminal_id: str = "",
    state: str = "",
    slug: str = "",
    cwd: str = "",
    branch: str = "",
    artifacts: tuple[str, ...] | list[str] = (),
    title: str = "",
) -> Workstream | None:
    """Move the supplied session/tab from any active Workstream to this Workstream."""
    if not workstream_id:
        return None
    data = _load()
    if workstream_id not in data.get("workstreams", {}):
        return None
    _remove_active_bindings(data, session_id=session_id, terminal_id=terminal_id, keep_workstream_id=workstream_id)
    return _save_workstream(
        data,
        workstream_id,
        session_id=session_id,
        terminal_id=terminal_id,
        state=state,
        slug=slug,
        cwd=cwd,
        branch=branch,
        artifacts=_clean_artifacts(artifacts),
        title=title,
    )


def resolve_active(session_id: str = "", terminal_id: str = "") -> Workstream | None:
    """Resolve an active session/tab binding only."""
    data = _load()
    wid = _find_active_workstream_id(data, session_id=session_id, terminal_id=terminal_id)
    return _workstream_by_id(data, wid)


def resolve_by_artifact(artifacts: tuple[str, ...] | list[str] = ()) -> Workstream | None:
    """Resolve an explicit artifact attachment only."""
    data = _load()
    wid = _find_artifact_workstream_id(data, _clean_artifacts(artifacts))
    return _workstream_by_id(data, wid)


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
    wid = _find_active_workstream_id(data, session_id=old_session_id, terminal_id=terminal_id)
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


def _find_active_workstream_id(data: dict, session_id: str = "", terminal_id: str = "") -> str:
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
    return ""


def _find_artifact_workstream_id(data: dict, artifacts: tuple[str, ...] | list[str] = ()) -> str:
    artifact_set = set(_clean_artifacts(artifacts))
    if not artifact_set:
        return ""
    workstreams = data.get("workstreams", {})
    if not isinstance(workstreams, dict):
        return ""
    for wid, record in workstreams.items():
        if not isinstance(record, dict):
            continue
        if artifact_set.intersection(record.get("artifacts", [])):
            return wid
    return ""


def _workstream_by_id(data: dict, workstream_id: str) -> Workstream | None:
    if not workstream_id:
        return None
    record = data.get("workstreams", {}).get(workstream_id)
    return _to_workstream(record) if isinstance(record, dict) else None


def _save_workstream(
    data: dict,
    workstream_id: str,
    session_id: str = "",
    terminal_id: str = "",
    state: str = "",
    slug: str = "",
    cwd: str = "",
    branch: str = "",
    artifacts: tuple[str, ...] | list[str] = (),
    title: str = "",
) -> Workstream:
    workstreams = data.setdefault("workstreams", {})
    now = time.time()
    record = workstreams.get(workstream_id)
    if not isinstance(record, dict):
        record = {
            "id": workstream_id,
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
        workstreams[workstream_id] = record

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
    for artifact in _clean_artifacts(artifacts):
        _append_unique(record.setdefault("artifacts", []), artifact)
    record["updated_at"] = now

    _save(data)
    return _to_workstream(record)


def _remove_active_bindings(data: dict, session_id: str = "", terminal_id: str = "", keep_workstream_id: str = "") -> None:
    if not session_id and not terminal_id:
        return
    for wid, record in data.get("workstreams", {}).items():
        if wid == keep_workstream_id or not isinstance(record, dict):
            continue
        changed = False
        if session_id and _remove_value(record.setdefault("active_sessions", []), session_id):
            changed = True
        if terminal_id and _remove_value(record.setdefault("active_terminals", []), terminal_id):
            changed = True
        if changed:
            record["updated_at"] = time.time()


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
    tmp = f"{path}.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


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
