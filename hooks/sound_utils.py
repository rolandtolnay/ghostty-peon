"""Shared utilities for Claude Code Ghostty hooks.

Provides sound playback with per-session unit assignment,
and shared logging to a configurable hook log.
"""

import datetime
import hashlib
import json
import os
import random
import subprocess
import tempfile

import ghostty_tab
import runtime_config
import title_handoff
import title_state


def _namespace() -> str:
    """Runtime namespace for tmp/state paths. Defaults preserve Claude behavior."""
    return runtime_config.namespace()


LOG_FILE = runtime_config.log_file()
SOUND_LAST_DIR = runtime_config.sound_last_dir()
_LOG_DATE_FILE = runtime_config.log_date_file()
LOG_PREV_FILE = runtime_config.log_prev_file()

REPO_ROOT = runtime_config.repo_root()
SOUNDS_DIR = os.path.join(REPO_ROOT, "sounds")
VALID_CLASSES = ("orc", "human", "nightelf", "undead")
PLAYBACK_VOLUME = "0.07"

UNITS = {
    "orc": ["peon", "grunt", "headhunter", "witchdoctor", "tauren", "shadowhunter", "shaman"],
    "human": ["peasant", "footman", "knight", "rifleman", "sorceress", "gryphonrider", "priest"],
    "nightelf": ["archer", "huntress", "warden", "druidoftheclaw", "druidofthetalon", "demonhunter", "dryad"],
    "undead": ["acolyte", "cryptfiend", "necromancer", "ghoul", "abomination", "dreadlord", "banshee"],
}

# ── Emoji configuration ──────────────────────────────────────────────
# All tab-title emojis in one place. Change here to update everywhere.
EMOJI_WORKING = "\U0001f300"   # 🌀 — Claude is processing
EMOJI_QUESTION = "\u2b50"     # ⭐ — question / input needed
EMOJI_BLOCKED = "\U0001f525"  # 🔥 — permission prompt
EMOJI_READY = "\U0001f33f"    # 🌿 — done, no input needed
ALL_EMOJIS = (EMOJI_BLOCKED, EMOJI_QUESTION, EMOJI_WORKING, EMOJI_READY)

UNIT_ASSIGN_DIR = runtime_config.unit_assign_dir()
SESSION_INDEX_DIR = runtime_config.session_index_dir()
STALE_HOURS = 12

WEIGHT_STATE_DIR = runtime_config.weight_state_dir()
WEIGHT_STATE_FILE = runtime_config.weight_state_file()


def _rotate_log_on_new_day() -> None:
    """On day change, archive current log as prev and start fresh.

    Keeps two files: today's log (LOG_FILE) and yesterday's (LOG_PREV_FILE).
    This ensures a full day's logs are always available for end-of-day audits.
    """
    today = datetime.date.today().isoformat()
    try:
        last = open(_LOG_DATE_FILE).read().strip()
    except OSError:
        last = ""
    if last != today:
        try:
            # Archive current log as previous day's log
            if os.path.exists(LOG_FILE):
                # Overwrite prev with current (prev = yesterday, current = today)
                os.replace(LOG_FILE, LOG_PREV_FILE)
            with open(LOG_FILE, "w") as f:
                f.write(f"=== {today} ===\n")
            with open(_LOG_DATE_FILE, "w") as f:
                f.write(today)
        except OSError:
            pass


def log(session_id: str, hook: str, message: str) -> None:
    """Append a timestamped log line. Silent on failure."""
    try:
        _rotate_log_on_new_day()
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        sid = (session_id or "")[-6:] or "??????"
        with open(LOG_FILE, "a") as f:
            f.write(f"{ts} [{sid}] {hook:<10} | {message}\n")
    except Exception:
        pass


def _read_last_played(category_key: str) -> str:
    """Read the last played filename for a category. Returns '' on any failure."""
    try:
        return open(os.path.join(SOUND_LAST_DIR, category_key)).read().strip()
    except OSError:
        return ""


def _write_last_played(category_key: str, filename: str) -> None:
    """Persist the last played filename for a category. Silent on failure."""
    try:
        os.makedirs(SOUND_LAST_DIR, exist_ok=True)
        with open(os.path.join(SOUND_LAST_DIR, category_key), "w") as f:
            f.write(filename)
    except OSError:
        pass


# --- Weighted rotation state ---

def _default_weight_state() -> dict:
    return {"version": 1, "unit_pools": {}, "class_pool": {}}


def _load_weight_state() -> dict:
    try:
        with open(WEIGHT_STATE_FILE, "r") as f:
            state = json.load(f)
        if isinstance(state, dict) and state.get("version") == 1:
            return state
    except FileNotFoundError:
        return _default_weight_state()
    except (json.JSONDecodeError, OSError):
        # Corrupt file — log and reset
        try:
            with open(LOG_FILE, "a") as lf:
                ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
                lf.write(f"{ts} [weight] sound      | weights.json corrupt, resetting\n")
        except OSError:
            pass
    return _default_weight_state()


def _save_weight_state(state: dict) -> None:
    try:
        os.makedirs(WEIGHT_STATE_DIR, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=WEIGHT_STATE_DIR, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_path, WEIGHT_STATE_FILE)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    except OSError:
        pass


def _get_pool_key(sound_class: str, mode: str) -> str:
    return f"{mode}:{sound_class}"


def _ensure_unit_pool(state: dict, pool_key: str, sound_class: str) -> dict:
    pools = state.setdefault("unit_pools", {})
    pool = pools.setdefault(pool_key, {"counts": {}, "last_unit": ""})
    counts = pool.setdefault("counts", {})
    for unit in UNITS.get(sound_class, []):
        if unit not in counts:
            counts[unit] = 0
    return pool


def _ensure_class_pool(state: dict) -> dict:
    pool = state.setdefault("class_pool", {"counts": {}, "last_class": ""})
    counts = pool.setdefault("counts", {})
    for cls in VALID_CLASSES:
        if cls not in counts:
            counts[cls] = 0
    return pool


def _weighted_choice(candidates: list[str], counts: dict, pool_size: int) -> str:
    weights = [100 / (pool_size + 3 * counts.get(c, 0)) for c in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


def _check_cycle_reset(counts: dict) -> bool:
    return bool(counts) and all(v > 0 for v in counts.values())


# --- Session unit assignment ---

def _project_key(cwd: str) -> str:
    """Short, filesystem-safe hash of the working directory."""
    return hashlib.sha256(cwd.encode()).hexdigest()[:12]


def _clean_stale(project_dir: str) -> None:
    """Delete assignment files older than STALE_HOURS."""
    try:
        cutoff = datetime.datetime.now().timestamp() - STALE_HOURS * 3600
        for name in os.listdir(project_dir):
            path = os.path.join(project_dir, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                pass
    except OSError:
        pass


def assign_unit(session_id: str, cwd: str) -> str | None:
    """Assign a unique unit to this session within its project.

    Uses weighted rotation so all units (and classes in random mode) get
    equal airtime across sessions and projects.

    Returns the unit name, or None if sounds are disabled.
    """
    try:
        env_class = os.environ.get("PEON_SOUND_CLASS", "random").lower().strip()
        if env_class == "none":
            return None

        is_random = env_class == "random"
        mode = "random" if is_random else "configured"

        weight_state = _load_weight_state()

        # --- Class selection ---
        if is_random:
            class_pool = _ensure_class_pool(weight_state)
            class_counts = class_pool["counts"]
            candidates = list(VALID_CLASSES)
            # Exclude last class if multiple candidates
            if len(candidates) > 1 and class_pool.get("last_class") in candidates:
                candidates = [c for c in candidates if c != class_pool["last_class"]]
            sound_class = _weighted_choice(candidates, class_counts, len(VALID_CLASSES))
            class_counts[sound_class] = class_counts.get(sound_class, 0) + 1
            if _check_cycle_reset(class_counts):
                for k in class_counts:
                    class_counts[k] = 0
            class_pool["last_class"] = sound_class
        else:
            sound_class = env_class
            if sound_class not in VALID_CLASSES:
                return None

        # --- Active-session exclusion ---
        pkey = _project_key(cwd)
        project_dir = os.path.join(UNIT_ASSIGN_DIR, pkey)
        os.makedirs(project_dir, exist_ok=True)
        _clean_stale(project_dir)

        assigned_units = set()
        for name in os.listdir(project_dir):
            if name == session_id:
                continue
            path = os.path.join(project_dir, name)
            try:
                lines = open(path).read().strip().split("\n")
                if len(lines) >= 2:
                    assigned_units.add(lines[1])
            except OSError:
                pass

        units = UNITS[sound_class]
        available = [u for u in units if u not in assigned_units]
        if not available:
            available = list(units)

        # --- Weighted unit selection ---
        pool_key = _get_pool_key(sound_class, mode)
        unit_pool = _ensure_unit_pool(weight_state, pool_key, sound_class)
        unit_counts = unit_pool["counts"]

        candidates = list(available)
        if len(candidates) > 1 and unit_pool.get("last_unit") in candidates:
            candidates = [c for c in candidates if c != unit_pool["last_unit"]]

        unit = _weighted_choice(candidates, unit_counts, len(units))
        unit_counts[unit] = unit_counts.get(unit, 0) + 1
        if _check_cycle_reset(unit_counts):
            for k in unit_counts:
                unit_counts[k] = 0
        unit_pool["last_unit"] = unit

        # --- Persist state ---
        _save_weight_state(weight_state)

        # Write assignment file
        assign_path = os.path.join(project_dir, session_id)
        with open(assign_path, "w") as f:
            f.write(f"{sound_class}\n{unit}")

        # Write session index file (for fast O(1) lookup in play_sound)
        os.makedirs(SESSION_INDEX_DIR, exist_ok=True)
        with open(os.path.join(SESSION_INDEX_DIR, session_id), "w") as f:
            f.write(pkey)

        return unit
    except Exception:
        return None


def release_unit(session_id: str, cwd: str) -> None:
    """Remove session's unit assignment. Silent on failure."""
    try:
        pkey = _project_key(cwd)
        assign_path = os.path.join(UNIT_ASSIGN_DIR, pkey, session_id)
        try:
            os.remove(assign_path)
        except OSError:
            pass
        index_path = os.path.join(SESSION_INDEX_DIR, session_id)
        try:
            os.remove(index_path)
        except OSError:
            pass
    except Exception:
        pass


def _get_session_unit(session_id: str) -> tuple[str, str] | None:
    """Look up the stored class and unit for a session.

    Returns (class, unit) or None if no assignment found.
    """
    try:
        index_path = os.path.join(SESSION_INDEX_DIR, session_id)
        pkey = open(index_path).read().strip()
        assign_path = os.path.join(UNIT_ASSIGN_DIR, pkey, session_id)
        lines = open(assign_path).read().strip().split("\n")
        if len(lines) >= 2:
            return (lines[0], lines[1])
    except OSError:
        pass
    return None


def capture_terminal_id(session_id: str) -> str | None:
    """Capture the Ghostty terminal UUID for the currently focused tab."""
    return ghostty_tab.capture_terminal_id(session_id)


def is_terminal_owned(term_id: str, exclude_session: str) -> str | None:
    """Check if another session already owns this terminal."""
    return ghostty_tab.is_terminal_owned(term_id, exclude_session)


def clear_terminal_owner(term_id: str, exclude_session: str) -> str | None:
    """Remove a stale/replaced terminal owner and return its session id."""
    return ghostty_tab.clear_terminal_owner(term_id, exclude_session)


def get_terminal_id(session_id: str) -> str | None:
    """Read the persisted Ghostty terminal UUID for a session."""
    return ghostty_tab.get_terminal_id(session_id)


def release_terminal_id(session_id: str) -> None:
    """Delete the persisted terminal ID for a session. Silent on failure."""
    ghostty_tab.release_terminal_id(session_id)


def write_plan_handoff(term_id: str, title: str) -> bool:
    """Persist a short-lived title handoff for Claude plan-mode session rollover."""
    return title_handoff.write(term_id, title)


def consume_plan_handoff(term_id: str, ttl_seconds: int = 120) -> str | None:
    """Read and delete a fresh plan handoff for a terminal, if one exists."""
    return title_handoff.consume(term_id, ttl_seconds=ttl_seconds)


def set_tab_title(title: str, session_id: str | None = None) -> bool:
    """Set a Ghostty tab title, targeting the session's specific terminal."""
    return ghostty_tab.set_tab_title(title, session_id, log_fn=log)


def is_tab_focused(session_id: str) -> bool:
    """Check if the session's Ghostty tab is currently focused."""
    return ghostty_tab.is_tab_focused(session_id)


def set_attention_emoji(
    session_id: str,
    emoji: str,
    clean_title: str,
    timestamp: str,
    hook_name: str,
) -> bool:
    """Set attention emoji on tab title and play input.required sound if not focused.

    Sets the emoji, writes debounce state, and plays the sound only when the
    user is NOT looking at this tab. Returns True if title was set successfully.
    """
    new_title = f"{emoji} {clean_title}"
    if not set_tab_title(new_title, session_id):
        log(session_id, hook_name, f"set_tab_title failed for {new_title!r}")
        return False

    if is_tab_focused(session_id):
        log(session_id, hook_name, "skip sound: tab is focused")
    else:
        play_sound("input.required", session_id)

    # Persist emoji state in debounce file
    try:
        title_state.write(session_id, timestamp, new_title)
    except OSError as e:
        log(session_id, hook_name, f"debounce write failed: {e}")

    log(session_id, hook_name, f"set -> {new_title!r}")
    return True


def strip_all_emojis(title: str) -> str:
    """Remove any leading status emoji from title."""
    for emoji in ALL_EMOJIS:
        if title.startswith(emoji):
            title = title[len(emoji):].lstrip()
    return title


def set_status_emoji(
    session_id: str,
    emoji: str,
    clean_title: str,
    timestamp: str,
    hook_name: str,
) -> bool:
    """Set a status emoji on tab title WITHOUT playing sound.

    Used for passive indicators (working, ready) as opposed to
    set_attention_emoji which plays input.required for active alerts.
    """
    new_title = f"{emoji} {clean_title}"
    if not set_tab_title(new_title, session_id):
        log(session_id, hook_name, f"set_tab_title failed for {new_title!r}")
        return False

    # Persist emoji state in debounce file
    try:
        title_state.write(session_id, timestamp, new_title)
    except OSError as e:
        log(session_id, hook_name, f"debounce write failed: {e}")

    log(session_id, hook_name, f"set -> {new_title!r}")
    return True


def play_sound(event: str, session_id: str | None = None) -> None:
    """Play a random sound for the given event (e.g. 'session.start').

    If session_id is provided, uses the stored class/unit assignment.
    Falls back to env var + random unit if no assignment found.
    """
    try:
        sound_class = None
        unit = None
        source = "stored"

        # Try stored assignment first
        if session_id:
            result = _get_session_unit(session_id)
            if result:
                sound_class, unit = result

        # Fallback: read env var
        if not sound_class:
            source = "env"
            sound_class = os.environ.get("PEON_SOUND_CLASS", "random").lower().strip()
            if sound_class == "none":
                if session_id:
                    log(session_id, "sound", f"skip {event}: class=none")
                return
            if sound_class == "random":
                sound_class = random.choice(VALID_CLASSES)
            if sound_class not in VALID_CLASSES:
                if session_id:
                    log(session_id, "sound", f"skip {event}: invalid class={sound_class!r}")
                return
            unit = random.choice(UNITS[sound_class])

        sound_dir = os.path.join(SOUNDS_DIR, sound_class, unit, event)
        if not os.path.isdir(sound_dir):
            if session_id:
                log(session_id, "sound", f"skip {event}: dir missing ({sound_class}/{unit}/{event})")
            return

        files = [f for f in os.listdir(sound_dir) if os.path.isfile(os.path.join(sound_dir, f))]
        if not files:
            if session_id:
                log(session_id, "sound", f"skip {event}: no files in {sound_class}/{unit}/{event}")
            return

        # Avoid repeating the same sound twice in a row per category
        category_key = f"{sound_class}.{unit}.{event}"
        last_file = _read_last_played(category_key)
        if len(files) > 1 and last_file in files:
            files = [f for f in files if f != last_file]

        chosen = random.choice(files)
        _write_last_played(category_key, chosen)
        path = os.path.join(sound_dir, chosen)
        subprocess.Popen(
            ["afplay", "--volume", PLAYBACK_VOLUME, path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if session_id:
            log(session_id, "sound", f"{event} -> {sound_class}/{unit}/{chosen} ({source})")
    except Exception as e:
        if session_id:
            log(session_id, "sound", f"error on {event}: {e}")
