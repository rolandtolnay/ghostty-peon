"""Runtime namespace and path configuration for Ghostty Peon hooks.

All environment variable names and default paths are preserved here so runtime
adapters and hook modules do not each rebuild Pi/Claude tmp paths differently.
"""

from __future__ import annotations

import os


def namespace() -> str:
    """Runtime namespace for tmp/state paths. Defaults preserve Claude behavior."""
    value = os.environ.get("GHOSTTY_PEON_NAMESPACE", "claude").strip().lower()
    return value or "claude"


def tmp_path(name: str) -> str:
    return f"/tmp/{namespace()}-{name}"


def env_path(name: str, default: str) -> str:
    return os.environ.get(name, default)


def repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def log_file() -> str:
    return env_path("GHOSTTY_PEON_LOG_FILE", tmp_path("tab-hooks.log"))


def log_date_file() -> str:
    return env_path("GHOSTTY_PEON_LOG_DATE_FILE", tmp_path("tab-hooks.lastdate"))


def log_prev_file() -> str:
    return env_path("GHOSTTY_PEON_LOG_PREV_FILE", tmp_path("tab-hooks.prev.log"))


def sound_last_dir() -> str:
    return env_path("GHOSTTY_PEON_SOUND_LAST_DIR", tmp_path("sound-last"))


def debounce_dir() -> str:
    return env_path("GHOSTTY_PEON_DEBOUNCE_DIR", tmp_path("tabtitle"))


def plan_handoff_dir() -> str:
    return env_path("GHOSTTY_PEON_PLAN_HANDOFF_DIR", tmp_path("plan-handoff"))


def terminal_id_dir() -> str:
    return env_path("GHOSTTY_PEON_TERMINAL_ID_DIR", tmp_path("tabterminal"))


def unit_assign_dir() -> str:
    return env_path("GHOSTTY_PEON_UNIT_ASSIGN_DIR", tmp_path("sound-units"))


def session_index_dir() -> str:
    return env_path("GHOSTTY_PEON_SESSION_INDEX_DIR", tmp_path("sound-session"))


def weight_state_dir() -> str:
    return os.path.expanduser(env_path("GHOSTTY_PEON_WEIGHT_STATE_DIR", "~/.ghostty-peon"))


def default_weight_file_name() -> str:
    return "weights.json" if namespace() == "claude" else f"{namespace()}-weights.json"


def weight_state_file() -> str:
    default = os.path.join(weight_state_dir(), default_weight_file_name())
    return os.path.expanduser(env_path("GHOSTTY_PEON_WEIGHT_STATE_FILE", default))
