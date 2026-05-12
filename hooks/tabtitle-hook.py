#!/usr/bin/env python3
"""Auto-rename the current Ghostty tab based on conversation topic.

Triggered on UserPromptSubmit. Calls local Ollama model (Qwen3.5-4B)
to generate an action-oriented slug (e.g. fix-ghostty-tab-targeting),
then sets the Ghostty tab title via AppleScript.

Uses conversation context for better slug generation: the message that
established the current title (origin), recent user messages, and the
current prompt. This lets the model detect meaningful topic shifts.

Debounces by session: skips if renamed within the last 90 seconds,
and ignores short prompts (< 40 chars) that are unlikely to shift topic.
The first user message in a session always triggers a rename.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sound_utils import (
    ALL_EMOJIS,
    DEBOUNCE_DIR,
    EMOJI_WORKING,
    log,
    play_sound,
    set_status_emoji,
    set_tab_title,
    strip_all_emojis,
)

COOLDOWN_SECONDS = 90
MIN_PROMPT_LENGTH = 40
MAX_MSG_CHARS = 3000

# Prompts to completely ignore — no rename, no history, no side effects.
IGNORED_PROMPTS = [
    "/commit-commands:commit",
]


def get_debounce_path(session_id: str) -> str:
    return os.path.join(DEBOUNCE_DIR, f"{session_id}")


def get_origin_path(session_id: str) -> str:
    return os.path.join(DEBOUNCE_DIR, f"{session_id}.origin")


def should_skip(session_id: str, prompt: str) -> str | None:
    """Return a skip reason string, or None to proceed."""
    debounce_path = get_debounce_path(session_id)

    # First message always triggers (no debounce file yet)
    if not os.path.exists(debounce_path):
        return None

    # Short prompts never trigger (after the first message)
    if len(prompt.strip()) < MIN_PROMPT_LENGTH:
        return f"prompt too short ({len(prompt.strip())} < {MIN_PROMPT_LENGTH} chars)"

    # Check cooldown
    try:
        last_time = float(open(debounce_path).read().split("\n")[0].strip())
        elapsed = time.time() - last_time
        if elapsed < COOLDOWN_SECONDS:
            return f"cooldown ({elapsed:.0f}s elapsed, {COOLDOWN_SECONDS}s required)"
    except (ValueError, OSError):
        pass

    return None


def get_current_title(debounce_path: str) -> str:
    """Read the current title from the debounce file (second line)."""
    try:
        lines = open(debounce_path).read().strip().split("\n")
        if len(lines) >= 2:
            return strip_emoji(lines[1])
    except OSError:
        pass
    return ""


def get_debounce_timestamp(debounce_path: str) -> str:
    try:
        lines = open(debounce_path).read().strip().split("\n")
        if lines and lines[0]:
            return lines[0]
    except OSError:
        pass
    return "0"


def write_debounce(debounce_path: str, timestamp: str, title: str, session_id: str = "") -> None:
    try:
        os.makedirs(DEBOUNCE_DIR, exist_ok=True)
        with open(debounce_path, "w") as f:
            f.write(f"{timestamp}\n{title}")
    except OSError as e:
        if session_id:
            log(session_id, "tabtitle", f"debounce write failed: {e}")


def get_origin_message(session_id: str) -> str:
    """Read the origin message that established the current title."""
    try:
        return open(get_origin_path(session_id)).read()
    except OSError:
        return ""


def write_origin_message(session_id: str, message: str) -> None:
    """Store the message that established the current title."""
    os.makedirs(DEBOUNCE_DIR, exist_ok=True)
    with open(get_origin_path(session_id), "w") as f:
        f.write(message[:MAX_MSG_CHARS])


def strip_emoji(title: str) -> str:
    """Remove any leading status emoji from title."""
    return strip_all_emojis(title)


def get_transcript_path(data: dict, session_id: str) -> str:
    """Get transcript path from event data or derive from CWD."""
    path = data.get("transcript_path", "")
    if path and os.path.exists(path):
        return path
    cwd = data.get("cwd", os.getcwd())
    encoded = cwd.replace("/", "-")
    home = os.path.expanduser("~")
    derived = os.path.join(home, ".claude", "projects", encoded, f"{session_id}.jsonl")
    if os.path.exists(derived):
        return derived
    return ""


def get_recent_user_messages(
    transcript_path: str, current_prompt: str, count: int = 2
) -> list[str]:
    """Extract the last N user messages from the transcript, excluding current prompt."""
    if not transcript_path or not os.path.exists(transcript_path):
        return []

    user_messages: list[str] = []
    try:
        with open(transcript_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = entry.get("message", {})
                if not isinstance(message, dict):
                    continue
                if message.get("role") == "user":
                    content = message.get("content", "")
                    text = ""
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        texts = []
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                texts.append(block.get("text", ""))
                        text = "\n".join(texts)
                    if text.strip() and text.strip() not in IGNORED_PROMPTS:
                        user_messages.append(text[:MAX_MSG_CHARS])
    except OSError:
        return []

    # Deduplicate: if last transcript message matches current prompt, skip it
    if user_messages and user_messages[-1][:200] == current_prompt[:200]:
        user_messages = user_messages[:-1]

    return user_messages[-count:] if user_messages else []


def generate_slug(
    prompt: str,
    current_title: str,
    origin_message: str = "",
    recent_messages: list[str] | None = None,
    session_id: str = "",
) -> str | None:
    """Call local Ollama model to generate a tab title slug."""
    system = (
        "You label terminal tabs so a developer can find the right coding session at a glance.\n"
        "Generate a lowercase hyphenated slug (3-5 words) or output KEEP.\n"
        "Start with a specific action verb: fix, add, refactor, implement, extract, migrate, remove, replace, create, evaluate, plan, debug, configure, restore, test, investigate, triage, update, review, setup.\n"
        "Short commands: slugify directly ('/work-ticket MIN-163' → 'work-ticket-min-163')\n\n"
        "If the current title is not 'none', default to KEEP. Only rename when the user starts working on a different feature or problem.\n\n"
        "KEEP — same task, different angle:\n"
        "  title=fix-auth-token, msg='Handle refresh tokens too' → KEEP\n"
        "  title=fix-auth-token, msg='/consider:first-principles Is this right?' → KEEP\n"
        "  title=refactor-cache, msg='Verify those changes work' → KEEP\n"
        "  title=implement-rules-chat-ai, msg='Now add unit tests for it' → KEEP\n"
        "  title=add-csv-export, msg='I disagree, try X instead' → KEEP\n\n"
        "RENAME — new session or different feature:\n"
        "  title=none, msg='Extract the ghostty hooks into a separate repo' → extract-ghostty-peon-repo\n"
        "  title=none, msg='Block payout creation when there is no bank account' → block-payout-scheduling-no-eba\n"
        "  title=none, msg='I want to evaluate which Ollama models could replace Qwen' → evaluate-ollama-qwen-replacement\n"
        "  title=fix-auth-token, msg='Now work on the CSV export' → add-csv-export\n"
        "  title=refactor-cache, msg='Check the deploy pipeline' → debug-deploy-pipeline\n"
        "  title=create-branch, msg='The create-pr script path is wrong' → fix-pr-script-path\n\n"
        "Output the slug or KEEP. When in doubt, KEEP."
    )

    # Build context from conversation history
    parts = []
    if origin_message:
        parts.append(f"<title_origin>{origin_message}</title_origin>")
    for msg in (recent_messages or []):
        parts.append(f"<recent_message>{msg}</recent_message>")
    parts.append(f"<current_message>{prompt[:MAX_MSG_CHARS]}</current_message>")
    context = "\n".join(parts)

    user_msg = (
        f"<current_title>{current_title or 'none'}</current_title>\n"
        f"{context}\n"
        "Output only the slug:"
    )

    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from client import llm as call_llm

        raw = call_llm(
            user_msg,
            system=system,
            temperature=0.1,
            max_tokens=20,
            num_ctx=4096,
            tag="tabtitle",
            timeout=10,
        )
        slug = raw.strip().strip('"').strip("`").lower()
        if not slug:
            log(session_id, "tabtitle", "slug empty after strip")
            return None
        if slug == "keep":
            return None
        if not is_valid_slug(slug):
            log(session_id, "tabtitle", f"slug failed validation: {slug!r}")
            return None
        return slug
    except Exception as e:
        log(session_id, "tabtitle", f"llm error: {e}")
        return None


def is_valid_slug(slug: str) -> bool:
    """Reject anything that isn't a clean hyphenated slug."""
    if len(slug) > 60:
        return False
    if " " in slug:
        return False
    if "error" in slug or "max turns" in slug or "truncat" in slug:
        return False
    if not any(c.isalpha() for c in slug):
        return False
    if not all(c.isalnum() or c == "-" for c in slug):
        return False
    return True


def main():
    # Guard against recursive execution from nested claude subprocesses
    if os.environ.get("_CLAUDE_HOOK_NESTED"):
        sys.exit(0)

    data = json.load(sys.stdin)
    prompt = data.get("prompt", "")
    session_id = data.get("session_id", "unknown")

    # Completely ignore certain prompts — no rename, no emoji clear, no side effects
    if prompt.strip() in IGNORED_PROMPTS:
        log(session_id, "tabtitle", f"skip: ignored prompt ({prompt.strip()!r})")
        sys.exit(0)

    log(session_id, "tabtitle", f"prompt={len(prompt)}chars")

    # Replace any previous emoji with 🌊 working indicator
    debounce_path = get_debounce_path(session_id)
    current_title = get_current_title(debounce_path)
    current_timestamp = get_debounce_timestamp(debounce_path)
    if current_title:
        log(session_id, "tabtitle", f"-> {EMOJI_WORKING} working ({current_title!r})")
        set_status_emoji(session_id, EMOJI_WORKING, current_title, current_timestamp, "tabtitle")
    else:
        log(session_id, "tabtitle", f"skip {EMOJI_WORKING}: no established title yet")

    skip_reason = should_skip(session_id, prompt)
    if skip_reason:
        log(session_id, "tabtitle", f"skip: {skip_reason}")
        sys.exit(0)

    # Gather conversation context
    is_first_message = not os.path.exists(debounce_path)
    origin_message = ""
    recent_messages = []
    if is_first_message:
        # Clean stale origin file (e.g., after /clear deletes debounce)
        try:
            os.remove(get_origin_path(session_id))
        except OSError:
            pass
    else:
        origin_message = get_origin_message(session_id)
        transcript_path = get_transcript_path(data, session_id)
        recent_messages = get_recent_user_messages(transcript_path, prompt, count=1)

    log(
        session_id,
        "tabtitle",
        f"calling llm (current={current_title!r}, origin={len(origin_message)}chars, recent={len(recent_messages)}msgs)",
    )
    slug = generate_slug(prompt, current_title, origin_message, recent_messages, session_id)
    log(session_id, "tabtitle", f"llm returned {slug!r}")

    now = str(time.time())
    if slug:
        if slug == current_title:
            # Same title — keep working emoji, preserve original timestamp (no cooldown reset)
            set_status_emoji(session_id, EMOJI_WORKING, current_title, current_timestamp, "tabtitle")
            log(session_id, "tabtitle", "slug == current title, cooldown not reset")
            sys.exit(0)
        # New slug — set with working emoji and reset cooldown
        log(session_id, "tabtitle", f"-> {EMOJI_WORKING} renamed ({slug!r})")
        if not set_status_emoji(session_id, EMOJI_WORKING, slug, now, "tabtitle"):
            log(session_id, "tabtitle", f"set_status_emoji failed for {slug!r}")
            sys.exit(0)
        play_sound("task.acknowledge", session_id)
        write_origin_message(session_id, prompt)
    else:
        if current_title:
            # No rename — keep working emoji, preserve original timestamp (no cooldown reset)
            set_status_emoji(session_id, EMOJI_WORKING, current_title, current_timestamp, "tabtitle")
        else:
            # First message, no title yet — just write timestamp
            write_debounce(debounce_path, now, "", session_id)
        if is_first_message:
            write_origin_message(session_id, prompt)
        log(session_id, "tabtitle", "no rename, cooldown not reset")

    sys.exit(0)


if __name__ == "__main__":
    main()
