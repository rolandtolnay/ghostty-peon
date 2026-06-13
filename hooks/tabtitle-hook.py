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

from dataclasses import dataclass
import html
import json
import os
import re
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runtime_config
import title_state
import workflow_judgment
import workflow_model
import workflow_state
from sound_utils import (
    EMOJI_WORKING,
    get_terminal_id,
    log,
    play_sound,
    set_status_emoji,
    skip_subagent_payload,
    strip_all_emojis,
)

COOLDOWN_SECONDS = 90
MIN_PROMPT_LENGTH = 40
MAX_MSG_CHARS = 3000
FALLBACK_WORKING_TITLE = "working"
FALLBACK_RETRY_TIMESTAMP = "0"
WORKFLOW_NO_SIGNAL = "no-signal"
WORKFLOW_APPLIED = "applied"
WORKFLOW_HANDLED_NO_TITLE = "handled-no-title"

# Prompts to completely ignore — no rename, no history, no side effects.
IGNORED_PROMPTS = [
    "/commit-commands:commit",
]

USER_REQUEST_RE = re.compile(r"<user-request>(.*?)</user-request>", re.IGNORECASE | re.DOTALL)

FALLBACK_STOPWORDS = {
    "a",
    "about",
    "an",
    "and",
    "attached",
    "bug",
    "can",
    "could",
    "diagnose",
    "for",
    "help",
    "i",
    "image",
    "in",
    "into",
    "is",
    "it",
    "look",
    "looking",
    "me",
    "of",
    "please",
    "screenshot",
    "see",
    "shown",
    "shows",
    "the",
    "this",
    "to",
    "with",
    "you",
}


def image_count_from_payload(data: dict) -> int:
    """Return image attachment count without requiring image bytes in hook payloads."""
    if "image_count" in data:
        image_count = data.get("image_count", 0)
        if isinstance(image_count, int):
            return max(image_count, 0)
        if isinstance(image_count, str):
            try:
                return max(int(image_count), 0)
            except ValueError:
                return 0
    images = data.get("images")
    if isinstance(images, list):
        return len(images)
    return 0


def fallback_slug_for_image_prompt(prompt: str) -> str:
    """Build a conservative title when an image prompt is too contextual for the LLM."""
    raw_words = prompt.replace("/", " ").replace("_", " ").split()
    words = ["".join(c for c in token.lower() if c.isalnum()) for token in raw_words]
    words = [word for word in words if word]
    bug_words = {"bug", "broken", "crash", "error", "fail", "fails", "failing", "issue"}
    verb = "debug" if any(word in bug_words for word in words) else "investigate"
    topic = [word for word in words if word not in FALLBACK_STOPWORDS and not word.isdigit()]
    if not topic:
        topic = ["screenshot"]
    slug = "-".join([verb, *topic[:3]])
    return slug[:60].rstrip("-")


def fallback_title_for_cwd(cwd: str) -> str:
    """Return a cheap distinguishable fallback title for a project directory."""
    folder = os.path.basename(os.path.abspath(cwd or os.getcwd()))
    return folder or FALLBACK_WORKING_TITLE


def is_retryable_fallback_state(state: title_state.TitleState) -> bool:
    """Return True when a title was seeded only as a retryable fallback."""
    return state.timestamp == FALLBACK_RETRY_TIMESTAMP and bool(strip_all_emojis(state.title).strip())


def semantic_title_for_llm(state: title_state.TitleState) -> str:
    """Treat retryable fallback titles as no real title for slug generation."""
    if is_retryable_fallback_state(state):
        return ""
    return strip_all_emojis(state.title).strip()


def has_established_title(session_id: str) -> bool:
    """Return True only when debounce state has a real, non-fallback title."""
    state = title_state.read(session_id)
    clean_title = strip_all_emojis(state.title).strip()
    return bool(clean_title) and not is_retryable_fallback_state(state)


def canonical_slug_from_title(title: str) -> tuple[str, str]:
    """Return (state, slug) when a clean title already has a workflow prefix."""
    clean = strip_all_emojis(title).strip()
    for state in workflow_model.WORKFLOW_STATES:
        prefix = f"{state}-"
        if clean.startswith(prefix):
            slug = workflow_model.normalize_slug(clean[len(prefix):])
            if slug:
                return state, slug
    return "", ""


def workflow_artifact_candidates(data: dict, prompt: str, cook_metadata: dict | None = None) -> list[str]:
    """Collect observable artifact path candidates from hook payload metadata."""
    candidates: list[str] = []
    for key in ("workflow_artifacts", "artifact_candidates"):
        value = data.get(key)
        if isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, str))
    for key in (
        "cook_plan_source_path",
        "cook_plan_source_absolute_path",
        "source_path",
        "source_absolute_path",
    ):
        value = data.get(key)
        if isinstance(value, str):
            candidates.append(value)
    metadata = cook_metadata if isinstance(cook_metadata, dict) else data.get("cook_plan")
    if isinstance(metadata, dict):
        for key in ("sourcePath", "sourceAbsolutePath", "source_path", "source_absolute_path"):
            value = metadata.get(key)
            if isinstance(value, str):
                candidates.append(value)
    candidates.extend(artifact.path for artifact in workflow_model.extract_artifacts(prompt))
    candidates.extend(transcript_artifact_candidates(data))
    seen = set()
    cleaned: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            cleaned.append(candidate)
    return cleaned


def transcript_artifact_candidates(data: dict, max_entries: int = 20) -> list[str]:
    """Return workflow artifact paths mentioned in recent transcript entries."""
    session_file = data.get("transcript_path") or data.get("session_file")
    if not isinstance(session_file, str) or not session_file:
        return []
    try:
        with open(session_file) as f:
            lines = f.readlines()[-max_entries:]
    except OSError:
        return []

    candidates: list[str] = []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        for text in transcript_entry_texts(entry):
            candidates.extend(artifact.path for artifact in workflow_model.extract_artifacts(text))
    return candidates


def transcript_entry_texts(entry: object) -> list[str]:
    if not isinstance(entry, dict):
        return []
    texts: list[str] = []

    message = entry.get("message")
    if isinstance(message, dict):
        texts.extend(content_texts(message.get("content")))

    texts.extend(content_texts(entry.get("content")))

    data = entry.get("data")
    if isinstance(data, dict):
        for key in ("readFiles", "writtenFiles", "workflow_artifacts", "artifact_candidates"):
            value = data.get(key)
            if isinstance(value, list):
                texts.extend(item for item in value if isinstance(item, str))

    return texts


def content_texts(content: object) -> list[str]:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    texts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str):
            texts.append(text)
    return texts


def cook_plan_metadata(data: dict) -> dict | None:
    direct = data.get("cook_plan")
    if _is_cook_plan_metadata(direct):
        return direct
    session_file = data.get("session_file") or data.get("transcript_path")
    if not isinstance(session_file, str) or not session_file:
        return None
    return read_cook_plan_metadata(session_file)


def read_cook_plan_metadata(session_file: str) -> dict | None:
    try:
        with open(session_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                metadata = _cook_plan_metadata_from_entry(entry)
                if metadata:
                    return metadata
    except OSError:
        return None
    return None


def _cook_plan_metadata_from_entry(entry: object) -> dict | None:
    if not isinstance(entry, dict):
        return None
    candidates = []
    for key in ("metadata", "data", "payload"):
        value = entry.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    candidates.append(entry)
    for candidate in candidates:
        if _is_cook_plan_metadata(candidate):
            return candidate
    return None


def _is_cook_plan_metadata(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    markers = [value.get("kind"), value.get("type"), value.get("customType"), value.get("name")]
    if "cook-plan" in markers:
        return True
    nested = value.get("metadata")
    return isinstance(nested, dict) and _is_cook_plan_metadata(nested)


def current_branch_name(cwd: str) -> str:
    if not isinstance(cwd, str) or not cwd:
        return ""
    commands = (
        ["git", "symbolic-ref", "--short", "HEAD"],
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
    )
    for command in commands:
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                text=True,
                capture_output=True,
                timeout=1,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode != 0:
            continue
        branch = result.stdout.strip()
        if branch and branch != "HEAD":
            return branch
    return ""


def should_skip(session_id: str, prompt: str) -> str | None:
    """Return a skip reason string, or None to proceed."""
    # First message always triggers (no debounce file yet)
    if not title_state.exists(session_id):
        return None

    # Short prompts never trigger (after the first message)
    if len(prompt.strip()) < MIN_PROMPT_LENGTH:
        return f"prompt too short ({len(prompt.strip())} < {MIN_PROMPT_LENGTH} chars)"

    # If the session still only has an empty/fallback title, keep retrying on
    # substantive prompts instead of letting a failed LLM call trap the tab with
    # no useful state for the attention/ready emoji hooks.
    if not has_established_title(session_id):
        return None

    # Check cooldown
    try:
        last_time = float(title_state.read(session_id).timestamp)
        elapsed = time.time() - last_time
        if elapsed < COOLDOWN_SECONDS:
            return f"cooldown ({elapsed:.0f}s elapsed, {COOLDOWN_SECONDS}s required)"
    except ValueError:
        pass

    return None


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


def extract_skill_user_request(text: str) -> str:
    """Return the original user request from a Pi skill-expanded prompt when present."""
    if not isinstance(text, str):
        return ""
    lowered = text.lower()
    if "<skill" not in lowered or "<user-request" not in lowered:
        return ""
    requests = []
    for match in USER_REQUEST_RE.finditer(text):
        request = html.unescape(match.group(1)).strip()
        if request:
            requests.append(request)
    return "\n\n".join(requests)


def title_model_prompt_text(prompt: str) -> str:
    """Return the user-authored text that should be shown to title LLMs."""
    return extract_skill_user_request(prompt) or prompt


def get_recent_user_messages(
    transcript_path: str, current_prompt: str, count: int = 2
) -> list[str]:
    """Extract recent user-authored messages from the transcript, excluding current prompt."""
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
                    normalized = title_model_prompt_text(text).strip()
                    if (
                        normalized
                        and text.strip() not in IGNORED_PROMPTS
                        and normalized not in IGNORED_PROMPTS
                    ):
                        user_messages.append(normalized[:MAX_MSG_CHARS])
    except OSError:
        return []

    # Deduplicate: if last transcript message matches the current prompt after
    # skill-envelope normalization, skip it.
    current_normalized = title_model_prompt_text(current_prompt).strip()
    if user_messages and user_messages[-1][:200] == current_normalized[:200]:
        user_messages = user_messages[:-1]

    return user_messages[-count:] if user_messages else []


def conversation_context(data: dict, session_id: str, prompt: str, is_first_message: bool) -> tuple[str, list[str]]:
    if is_first_message:
        title_state.delete_origin(session_id)
        return "", []
    origin_message = title_state.read_origin(session_id)
    transcript_path = get_transcript_path(data, session_id)
    return origin_message, get_recent_user_messages(transcript_path, prompt, count=2)


@dataclass(frozen=True)
class SlugGenerationResult:
    slug: str | None = None
    timed_out: bool = False


def is_timeout_error(error: Exception) -> bool:
    """Return True for urllib/socket timeout failures from the local LLM call."""
    return isinstance(error, (TimeoutError, socket.timeout)) or "timed out" in str(error).lower()


def generate_slug_result(
    prompt: str,
    current_title: str,
    origin_message: str = "",
    recent_messages: list[str] | None = None,
    session_id: str = "",
    image_count: int = 0,
) -> SlugGenerationResult:
    """Call local Ollama model to generate a tab title slug with failure status."""
    system = (
        'You label terminal tabs so a developer can find the right coding session at a glance.\n'
        'Output either KEEP or a lowercase hyphenated slug, usually 2-5 words.\n'
        'Start slugs with a specific action verb when the task has one: fix, add, refactor, implement, extract, migrate, remove, replace, create, evaluate, plan, debug, configure, restore, test, investigate, triage, update, review, setup.\n'
        '\n'
        'DECISION ORDER:\n'
        "1. If current_title is 'none' and current_message is concrete, create a slug from current_message.\n"
        "2. If current_title is 'none' and current_message is a short slash command, ticket command, or mechanical command, slugify it directly. Do not output KEEP.\n"
        "3. If current_title is 'none' but current_message depends on missing previous context, output KEEP.\n"
        "4. If current_title is not 'none', default to KEEP when the message continues the same task. For same-task messages, output exactly KEEP; do not restate or shorten current_title. Framework slash commands like /consider, /analyze, or /verify with an existing title are same-task tools, not new topics.\n"
        "5. If current_title is not 'none', rename when the user starts a different feature or problem. New-topic wording such as 'new problem', 'separate task', 'switch to', 'different direction', 'unrelated', 'next', 'now I want', 'actually build/add/fix/create', or asking about a different command/component usually means rename.\n"
        "6. If recent_message introduced a future task and current_message says 'do that now', title the future task from recent_message/current_message, not the stale current_title.\n"
        '\n'
        'Never output none. Never output a slug starting with keep-. KEEP must be the exact token KEEP.\n'
        '\n'
        'SHORT COMMANDS — title=none, slugify directly:\n'
        "  title=none, msg='/work-ticket MIN-163' → work-ticket-min-163\n"
        "  title=none, msg='/work-ticket MIN-159' → work-ticket-min-159\n"
        "  title=none, msg='/prime meta' → prime-meta\n"
        "  title=none, msg='/audit-prompt 9bdbf42' → audit-prompt-9bdbf42\n"
        "  title=none, msg='can you amend the last commit with these changes' → amend-last-commit\n"
        "  title=none, msg='Use a verifier agent to confirm checkout discount behavior' → verify-checkout-discounts\n"
        "  title=none, msg='Compare several note-taking apps for a writing workflow' → compare-notes-apps\n"
        '\n'
        'AMBIGUOUS NEW SESSION — title=none, no standalone topic:\n'
        "  title=none, msg='Can you present the plan again for approval?' → KEEP\n"
        "  title=none, msg='Can you implement the second option?' → KEEP\n"
        "  title=none, msg='Make it better but keep the same approach' → KEEP\n"
        '\n'
        'KEEP — same task, different angle:\n'
        "  title=fix-auth-token, msg='Handle refresh tokens too' → KEEP\n"
        "  title=fix-auth-token, msg='/consider:first-principles Is this right?' → KEEP\n"
        "  title=work-ticket-min-159, msg='/consider:first-principles Is the plan boolean the best name?' → KEEP\n"
        "  title=work-ticket-min-159, msg='/consider:first-principles Should we rename this boolean?' → KEEP\n"
        "  title=review-user-interviewing-soft-caps, msg='/analyze-problem brainstorm the best solution' → KEEP\n"
        "  title=fix-tax-rate-drawer-modal, msg='Verify all the changes from this session' → KEEP\n"
        "  title=refactor-cache, msg='Verify those changes work' → KEEP\n"
        "  title=implement-rules-chat-ai, msg='Now add unit tests for it' → KEEP\n"
        "  title=add-csv-export, msg='I disagree, try X instead' → KEEP\n"
        "  title=configure-source-maps, msg='Make sure the auth token uses CI secrets' → KEEP\n"
        "  title=plan-invite-flow, msg='Go with the second option and write implementation steps' → KEEP\n"
        "  title=debug-websocket-reconnect, msg='Add a regression test for the reconnect path' → KEEP\n"
        '\n'
        'RENAME — new session or different feature:\n'
        "  title=none, msg='Extract the ghostty hooks into a separate repo' → extract-ghostty-peon-repo\n"
        "  title=none, msg='Plan the Mindsystem roadmap and phases' → plan-mindsystem-work-breakdown\n"
        "  title=none, msg='/ms:adhoc Fix Tax Rate Creation from Drawers' → fix-tax-rate-drawer-modal\n"
        "  title=none, msg='Block payout creation when there is no bank account' → block-payout-scheduling-no-eba\n"
        "  title=none, msg='Evaluate whether TOON is a better output format' → evaluate-toon-output-format\n"
        "  title=fix-auth-token, msg='Now work on the CSV export' → add-csv-export\n"
        "  title=refactor-cache, msg='Check the deploy pipeline' → debug-deploy-pipeline\n"
        "  title=create-branch, msg='The create-pr script path is wrong' → fix-pr-script-path\n"
        "  title=create-branch, msg='Can you check whether a different command has a script path error?' → fix-command-script-path\n"
        "  title=fix-login-bug, msg='Switch to adding billing webhooks now' → add-billing-webhooks\n"
        "  title=remove-legacy-auth, msg='Switch to analytics and add event tracking' → add-analytics-tracking\n"
        "  title=old-feature, msg='Investigate why uploaded avatars rotate sideways' → investigate-avatar-rotation\n"
        "  title=old-feature, msg='New problem: users get logged out' → debug-user-logout\n"
        "  title=old-feature, msg='Separate task: document keyboard shortcuts' → document-keyboard-shortcuts\n"
        "  title=old-feature, msg='Actually build fuzzy search first' → build-fuzzy-search\n"
        "  title=old-feature, msg='Now I want to redesign terminal theme colors' → redesign-terminal-theme\n"
        "  title=old-feature, msg='Next, fix mobile navigation accessibility labels' → fix-mobile-nav-accessibility\n"
        "  title=old-feature, msg='Do that now for analytics package dependencies' → update-analytics-dependencies\n"
        "  title=old-feature, msg='Unrelated: audit feature flags' → audit-feature-flags\n"
        '\n'
        'IMAGE ATTACHMENTS: You cannot see attached images. Use only the surrounding text to title the task. If title=none and images are attached, prefer a concrete text-derived slug; if the text has no concrete topic, use investigate-screenshot rather than KEEP.\n'
        'Final rule: With an existing non-none title, choose KEEP unless the topic clearly changed. With title=none and a concrete message, choose a slug.'
    )

    user_msg = build_llm_user_message(
        prompt,
        current_title,
        origin_message,
        recent_messages,
        image_count,
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
            return SlugGenerationResult()
        if slug == "keep":
            return SlugGenerationResult()
        if not is_valid_slug(slug):
            log(session_id, "tabtitle", f"slug failed validation: {slug!r}")
            return SlugGenerationResult()
        return SlugGenerationResult(slug=slug)
    except Exception as e:
        log(session_id, "tabtitle", f"llm error: {e}")
        return SlugGenerationResult(timed_out=is_timeout_error(e))


def generate_slug(
    prompt: str,
    current_title: str,
    origin_message: str = "",
    recent_messages: list[str] | None = None,
    session_id: str = "",
    image_count: int = 0,
) -> str | None:
    """Call local Ollama model to generate a tab title slug."""
    return generate_slug_result(
        prompt,
        current_title,
        origin_message,
        recent_messages,
        session_id,
        image_count,
    ).slug


def build_llm_user_message(
    prompt: str,
    current_title: str,
    origin_message: str = "",
    recent_messages: list[str] | None = None,
    image_count: int = 0,
) -> str:
    """Build the user message for the tab title LLM."""
    parts = []
    if origin_message:
        parts.append(f"<title_origin>{origin_message}</title_origin>")
    for msg in (recent_messages or []):
        parts.append(f"<recent_message>{msg}</recent_message>")
    if image_count:
        noun = "image" if image_count == 1 else "images"
        parts.append(
            f"<attachments>{image_count} {noun} attached; image contents are unavailable to the title generator.</attachments>"
        )
    parts.append(f"<current_message>{prompt[:MAX_MSG_CHARS]}</current_message>")
    context = "\n".join(parts)

    return (
        f"<current_title>{current_title or 'none'}</current_title>\n"
        f"{context}\n"
        "Output only the slug:"
    )


def set_fallback_working_title(session_id: str, cwd: str = "") -> bool:
    """Seed a visible, retryable title when slug generation fails initially."""
    fallback_title = fallback_title_for_cwd(cwd)
    log(session_id, "tabtitle", f"-> {EMOJI_WORKING} fallback ({fallback_title!r})")
    return set_status_emoji(
        session_id,
        EMOJI_WORKING,
        fallback_title,
        FALLBACK_RETRY_TIMESTAMP,
        "tabtitle",
    )


def is_valid_slug(slug: str) -> bool:
    """Reject anything that isn't a clean hyphenated slug."""
    if len(slug) > 60:
        return False
    if " " in slug:
        return False
    # Reject common failure text from model/tool wrappers, but allow legitimate
    # topic slugs like "debug-update-tool-error".
    invalid_exact = {
        "current-directory",
        "current-folder",
        "current-path",
        "error",
        "max-turns",
        "max-turns-reached",
        "truncated",
    }
    if slug in invalid_exact:
        return False
    is_error_prefix = slug.startswith("error-")
    is_simple_error_suffix = slug.endswith("-error") and slug.count("-") == 1
    if is_error_prefix or is_simple_error_suffix:
        return False
    if "max-turns" in slug or "truncat" in slug:
        return False
    if not any(c.isalpha() for c in slug):
        return False
    if not all(c.isalnum() or c == "-" for c in slug):
        return False
    return True


def workflow_transition_kind(is_first_message: bool, current_state: str, selected_skills: tuple[str, ...]) -> str:
    if workflow_model.deterministic_state(selected_skills):
        return ""
    if is_first_message and not current_state:
        return "ordinary-to-check"
    if current_state == workflow_model.CHECK:
        return "check-to-prep"
    if current_state == workflow_model.PLAN:
        return "plan-to-cook"
    return ""


def judge_workflow_transition(
    kind: str,
    prompt: str,
    current_state: str,
    current_title: str,
    origin_message: str,
    recent_messages: list[str],
    session_id: str,
) -> str:
    if not kind:
        return ""
    result = workflow_judgment.judge(
        workflow_judgment.JudgmentContext(
            kind=kind,
            prompt=prompt,
            current_state=current_state,
            current_title=current_title,
            origin_message=origin_message,
            recent_messages=tuple(recent_messages),
        )
    )
    log(session_id, "tabtitle", f"workflow judgment {kind} -> {result.transition or 'none'}")
    return result.transition


def maybe_apply_canonical_workflow(
    data: dict,
    session_id: str,
    prompt: str,
    title_prompt: str,
    current_title: str,
    semantic_current_title: str,
    current_timestamp: str,
    is_first_message: bool,
    origin_message: str,
    recent_messages: list[str],
    image_count: int,
) -> str:
    """Apply Pi Canonical Workflow Mode and report whether ordinary slug flow may continue."""
    if runtime_config.namespace() != "pi":
        return WORKFLOW_NO_SIGNAL

    cook_metadata = cook_plan_metadata(data)
    selected_skills = workflow_model.invoked_skill_names(prompt)
    if cook_metadata and "cook-plan" not in selected_skills:
        selected_skills = (*selected_skills, "cook-plan")
    signal_state = workflow_model.deterministic_state(selected_skills)
    artifact_candidates = workflow_artifact_candidates(data, prompt, cook_metadata)
    has_explicit_signal = bool(signal_state or artifact_candidates)
    term_id = get_terminal_id(session_id) or ""
    active_resolved = workflow_state.resolve_active(session_id=session_id, terminal_id=term_id)
    artifact_resolved = workflow_state.resolve_by_artifact(tuple(artifact_candidates)) if artifact_candidates else None
    starts_new_workstream = bool(
        active_resolved
        and not artifact_resolved
        and workflow_model.starts_new_workstream(active_resolved.state, signal_state)
    )
    resolved = artifact_resolved or (None if starts_new_workstream else active_resolved)

    title_state_name, title_slug = canonical_slug_from_title(current_title)
    active_binding = bool(active_resolved and resolved and active_resolved.id == resolved.id)
    current_workflow_state = resolved.state if resolved else (title_state_name if has_explicit_signal else "")
    inherited_slug = "" if starts_new_workstream else (
        (resolved.slug if resolved else "")
        or (title_slug if title_slug and (resolved or has_explicit_signal) else "")
        or semantic_current_title
    )
    artifact_binding_slug = artifact_resolved.slug if artifact_resolved else ""

    transition = judge_workflow_transition(
        workflow_transition_kind(is_first_message, current_workflow_state, selected_skills),
        title_prompt,
        current_workflow_state,
        current_title,
        origin_message,
        recent_messages,
        session_id,
    )

    def build_context(branch_name: str = "") -> workflow_model.WorkflowContext:
        return workflow_model.WorkflowContext(
            current_state=current_workflow_state,
            prompt="",
            selected_skills=selected_skills,
            artifact_candidates=tuple(artifact_candidates),
            branch_name=branch_name,
            inherited_slug=inherited_slug,
            transition=transition,
            active_binding=active_binding,
            artifact_binding_slug=artifact_binding_slug,
        )

    branch_name = ""
    decision = workflow_model.decide(build_context())
    if decision.needs_slug and decision.state in {workflow_model.COOK, workflow_model.REVIEW}:
        cwd = data.get("cwd", "") if isinstance(data.get("cwd"), str) else ""
        branch_name = current_branch_name(cwd)
        if branch_name:
            decision = workflow_model.decide(build_context(branch_name))

    if decision.needs_slug:
        slug_current_title = "" if starts_new_workstream else semantic_current_title
        log(
            session_id,
            "tabtitle",
            f"calling llm for workflow slug (state={decision.state!r}, current={slug_current_title!r})",
        )
        slug_result = generate_slug_result(
            title_prompt,
            slug_current_title,
            origin_message,
            recent_messages,
            session_id,
            image_count,
        )
        slug = slug_result.slug
        log(session_id, "tabtitle", f"workflow slug llm returned {slug!r}")
        if not slug and not current_title and image_count:
            slug = fallback_slug_for_image_prompt(title_prompt)
            log(session_id, "tabtitle", f"workflow image fallback returned {slug!r}")
        if not slug:
            log(session_id, "tabtitle", "workflow -> handled without title (missing slug)")
            return WORKFLOW_HANDLED_NO_TITLE
        decision = workflow_model.WorkflowDecision(workflow_model.ACTION_SET, decision.state, slug)

    if not decision.state or not decision.slug:
        if has_explicit_signal or active_resolved or artifact_resolved:
            log(session_id, "tabtitle", "workflow -> handled without title (no decision)")
            return WORKFLOW_HANDLED_NO_TITLE
        return WORKFLOW_NO_SIGNAL

    canonical_title = decision.canonical_title
    now = str(time.time())
    changed = canonical_title != current_title
    timestamp = now if changed else current_timestamp

    if not set_status_emoji(session_id, EMOJI_WORKING, canonical_title, timestamp, "tabtitle"):
        log(session_id, "tabtitle", f"workflow set_status_emoji failed for {canonical_title!r}")
        return WORKFLOW_APPLIED

    cwd = data.get("cwd", "") if isinstance(data.get("cwd"), str) else ""
    binding_args = {
        "session_id": session_id,
        "terminal_id": term_id,
        "state": decision.state,
        "slug": decision.slug,
        "cwd": cwd,
        "branch": branch_name,
        "artifacts": tuple(artifact_candidates),
        "title": canonical_title,
    }
    binding = workflow_model.binding_action(
        workflow_model.WorkflowBindingContext(
            active_workstream_id=active_resolved.id if active_resolved else "",
            artifact_workstream_id=artifact_resolved.id if artifact_resolved else "",
            starts_new_workstream=starts_new_workstream,
        )
    )
    if binding == workflow_model.BINDING_REPLACE_ACTIVE:
        workflow_state.replace_active_workstream(artifact_resolved.id, **binding_args)
    elif binding == workflow_model.BINDING_ATTACH_ARTIFACT:
        workflow_state.attach_to_existing_workstream(artifact_resolved.id, **binding_args)
    elif binding == workflow_model.BINDING_CREATE_REPLACING_ACTIVE:
        workflow_state.create_replacing_active_workstream(**binding_args)
    elif binding == workflow_model.BINDING_KEEP_ACTIVE:
        workflow_state.attach_to_existing_workstream(active_resolved.id, **binding_args)
    else:
        workflow_state.create_workstream(**binding_args)

    if decision.action == workflow_model.ACTION_KEEP or not changed:
        log(session_id, "tabtitle", f"workflow -> keep ({canonical_title!r})")
        return WORKFLOW_APPLIED

    log(session_id, "tabtitle", f"workflow -> {EMOJI_WORKING} renamed ({canonical_title!r})")
    play_sound("task.acknowledge", session_id)
    if is_first_message or not title_state.read_origin(session_id):
        title_state.write_origin(session_id, title_prompt, max_chars=MAX_MSG_CHARS)
    return WORKFLOW_APPLIED


def main():
    # Guard against recursive execution from nested claude subprocesses
    if os.environ.get("_CLAUDE_HOOK_NESTED"):
        sys.exit(0)

    data = json.load(sys.stdin)
    prompt = data.get("prompt", "")
    title_prompt = title_model_prompt_text(prompt)
    session_id = data.get("session_id", "unknown")
    if skip_subagent_payload(data, session_id, "tabtitle"):
        sys.exit(0)
    image_count = image_count_from_payload(data)

    # Completely ignore certain prompts — no rename, no emoji clear, no side effects
    if prompt.strip() in IGNORED_PROMPTS:
        log(session_id, "tabtitle", f"skip: ignored prompt ({prompt.strip()!r})")
        sys.exit(0)

    image_log = f", images={image_count}" if image_count else ""
    title_prompt_log = f", title_prompt={len(title_prompt)}chars" if title_prompt != prompt else ""
    log(session_id, "tabtitle", f"prompt={len(prompt)}chars{title_prompt_log}{image_log}")

    # Replace any previous emoji with 🌊 working indicator
    state = title_state.read(session_id)
    current_title = strip_emoji(state.title)
    semantic_current_title = semantic_title_for_llm(state)
    current_timestamp = state.timestamp
    is_first_message = not title_state.exists(session_id)
    origin_message, recent_messages = conversation_context(data, session_id, prompt, is_first_message)
    if current_title:
        log(session_id, "tabtitle", f"-> {EMOJI_WORKING} working ({current_title!r})")
        set_status_emoji(session_id, EMOJI_WORKING, current_title, current_timestamp, "tabtitle")
    else:
        log(session_id, "tabtitle", f"skip {EMOJI_WORKING}: no established title yet")

    workflow_result = maybe_apply_canonical_workflow(
        data,
        session_id,
        prompt,
        title_prompt,
        current_title,
        semantic_current_title,
        current_timestamp,
        is_first_message,
        origin_message,
        recent_messages,
        image_count,
    )
    if workflow_result != WORKFLOW_NO_SIGNAL:
        sys.exit(0)

    skip_reason = should_skip(session_id, title_prompt)
    if skip_reason:
        log(session_id, "tabtitle", f"skip: {skip_reason}")
        sys.exit(0)

    log(
        session_id,
        "tabtitle",
        f"calling llm (current={semantic_current_title!r}, origin={len(origin_message)}chars, recent={len(recent_messages)}msgs)",
    )
    slug_result = generate_slug_result(
        title_prompt,
        semantic_current_title,
        origin_message,
        recent_messages,
        session_id,
        image_count,
    )
    slug = slug_result.slug
    log(session_id, "tabtitle", f"llm returned {slug!r}")
    if not slug and not current_title and image_count:
        slug = fallback_slug_for_image_prompt(title_prompt)
        log(session_id, "tabtitle", f"image fallback returned {slug!r}")

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
        title_state.write_origin(session_id, title_prompt, max_chars=MAX_MSG_CHARS)
    else:
        if current_title:
            # No rename — keep working emoji, preserve original timestamp (no cooldown reset)
            set_status_emoji(session_id, EMOJI_WORKING, current_title, current_timestamp, "tabtitle")
        else:
            # First message, no semantic title yet — keep a visible working title
            # with timestamp 0 so the next substantive prompt retries immediately
            # instead of being blocked by cooldown.
            if slug_result.timed_out:
                set_fallback_working_title(session_id, data.get("cwd", ""))
            else:
                try:
                    title_state.write(session_id, now, "")
                except OSError as e:
                    log(session_id, "tabtitle", f"debounce write failed: {e}")
        if is_first_message:
            title_state.write_origin(session_id, title_prompt, max_chars=MAX_MSG_CHARS)
        log(session_id, "tabtitle", "no rename, cooldown not reset")

    sys.exit(0)


if __name__ == "__main__":
    main()
