"""Pure canonical workflow title model for Pi workstreams.

This module deliberately has no Ghostty, filesystem, sound, or LLM dependencies.
Callers pass observed runtime facts into ``decide`` and receive a title decision.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re

CHECK = "check"
PREP = "prep"
PLAN = "plan"
COOK = "cook"
REVIEW = "review"
WORKFLOW_STATES = (CHECK, PREP, PLAN, COOK, REVIEW)

ACTION_NONE = "none"
ACTION_SET = "set"
ACTION_KEEP = "keep"
ACTION_NEEDS_SLUG = "needs_slug"

BINDING_CREATE = "create"
BINDING_CREATE_REPLACING_ACTIVE = "create_replacing_active"
BINDING_KEEP_ACTIVE = "keep_active"
BINDING_ATTACH_ARTIFACT = "attach_artifact"
BINDING_REPLACE_ACTIVE = "replace_active"

_SKILL_STATE = {
    "prep": PREP,
    "to-prd": PREP,
    "plan": PLAN,
    "plan-quick": PLAN,
    "cook": COOK,
    "cook-plan": COOK,
    "review": REVIEW,
    "review-hard": REVIEW,
    "review-nuclear": REVIEW,
    "triage-pr-comments": REVIEW,
    "nuclear-reviewer": REVIEW,
}

_GENERIC_BRANCHES = {
    "",
    "head",
    "main",
    "master",
    "develop",
    "development",
    "dev",
    "trunk",
    "staging",
    "stage",
    "production",
    "prod",
    "release",
}
_SKILL_ENVELOPE_RE = re.compile(r"<skill\b[^>]*\bname=[\"']([^\"']+)[\"'][^>]*>", re.IGNORECASE)
_COMMAND_NAME = r"[\w:_-]+"
_BRACKET_COMMAND_RE = re.compile(rf"(?m)^\s*\[/({_COMMAND_NAME})\](?:[ \t]+([^\n]*))?\s*$")
_SLASH_COMMAND_RE = re.compile(rf"(?m)^\s*/({_COMMAND_NAME})(?:[ \t]+([^\n]*))?\s*$")
_PLACEHOLDER_PATH_RE = re.compile(r"(?:<[^/\\]+>|\{[^/\\]+\})")
_LIFECYCLE_COMMANDS = {
    "clear",
    "exit",
    "compact",
    "resume",
    "new",
    "fork",
    "clone",
    "tree",
    "init",
    "login",
    "logout",
    "status",
    "config",
    "help",
    "model",
    "settings",
    "session",
    "copy",
    "export",
    "share",
    "reload",
    "hotkeys",
    "changelog",
    "quit",
}
_CONTINUING_SIGNALS = {
    CHECK: {CHECK, PREP, PLAN},
    PREP: {PREP, PLAN, COOK},
    PLAN: {PLAN, COOK, REVIEW},
    COOK: {COOK, REVIEW},
    REVIEW: {REVIEW},
}


@dataclass(frozen=True)
class WorkflowArtifact:
    path: str
    kind: str
    slug: str


@dataclass(frozen=True)
class WorkflowContext:
    current_state: str = ""
    prompt: str = ""
    selected_skills: tuple[str, ...] = ()
    artifact_candidates: tuple[str, ...] = ()
    branch_name: str = ""
    inherited_slug: str = ""
    transition: str = ""
    active_binding: bool = False
    artifact_binding_slug: str = ""


@dataclass(frozen=True)
class WorkflowDecision:
    action: str = ACTION_NONE
    state: str = ""
    slug: str = ""

    @property
    def canonical_title(self) -> str:
        if not self.state or not self.slug:
            return ""
        return f"{self.state}-{self.slug}"

    @property
    def needs_slug(self) -> bool:
        return self.action == ACTION_NEEDS_SLUG


@dataclass(frozen=True)
class WorkflowBindingContext:
    active_workstream_id: str = ""
    artifact_workstream_id: str = ""
    starts_new_workstream: bool = False


def binding_action(context: WorkflowBindingContext) -> str:
    """Return the explicit persistence action for a canonical workflow decision."""
    active_id = context.active_workstream_id or ""
    artifact_id = context.artifact_workstream_id or ""
    if artifact_id and active_id and artifact_id != active_id:
        return BINDING_REPLACE_ACTIVE
    if artifact_id:
        return BINDING_ATTACH_ARTIFACT
    if active_id and context.starts_new_workstream:
        return BINDING_CREATE_REPLACING_ACTIVE
    if active_id:
        return BINDING_KEEP_ACTIVE
    return BINDING_CREATE


def starts_new_workstream(current_state: str, signal_state: str, transition_state: str = "") -> bool:
    """Return True when an explicit deterministic signal should replace active identity."""
    current = _normalize_state(current_state)
    signal = _normalize_state(signal_state)
    if not current or not signal or transition_state:
        return False
    return signal not in _CONTINUING_SIGNALS.get(current, set())


def decide(context: WorkflowContext) -> WorkflowDecision:
    """Return the canonical workflow title decision for observed facts."""
    signal_state = deterministic_state(context.selected_skills)
    transition_state = _normalize_state(context.transition)
    current_state = _normalize_state(context.current_state)
    artifacts = extract_artifacts(context.prompt, context.artifact_candidates)
    artifact_slug = preferred_artifact_slug(artifacts)

    target_state = signal_state or transition_state
    if not target_state and current_state and (context.active_binding or artifact_slug or context.artifact_binding_slug):
        target_state = current_state
    if not target_state:
        return WorkflowDecision()

    inherited_slug = normalize_slug(context.inherited_slug)
    artifact_binding_slug = normalize_slug(context.artifact_binding_slug)
    slug = _choose_slug(target_state, artifact_slug or artifact_binding_slug, inherited_slug, context.branch_name)
    if not slug:
        return WorkflowDecision(ACTION_NEEDS_SLUG, target_state, "")

    if current_state == target_state and inherited_slug == slug and not (signal_state or transition_state or artifact_slug):
        return WorkflowDecision(ACTION_KEEP, target_state, slug)
    return WorkflowDecision(ACTION_SET, target_state, slug)


def invoked_skill_names(prompt: str) -> tuple[str, ...]:
    """Return canonical skill names from explicit prompt invocation evidence."""
    if not isinstance(prompt, str) or not prompt:
        return ()

    names: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        name = _normalize_skill(raw)
        if not name or name in seen or name in _LIFECYCLE_COMMANDS:
            return
        seen.add(name)
        names.append(name)

    for match in _SKILL_ENVELOPE_RE.finditer(prompt):
        add(match.group(1))
    for regex in (_BRACKET_COMMAND_RE, _SLASH_COMMAND_RE):
        for match in regex.finditer(prompt):
            add(match.group(1))
    return tuple(names)


def deterministic_state(selected_skills: tuple[str, ...] | list[str]) -> str:
    for skill in selected_skills or ():
        normalized = _normalize_skill(skill)
        if normalized in _SKILL_STATE:
            return _SKILL_STATE[normalized]
    return ""


def _normalize_skill(skill: object) -> str:
    if not isinstance(skill, str):
        return ""
    normalized = skill.strip().lstrip("/").lower()
    if normalized.startswith("skill:"):
        normalized = normalized[len("skill:"):]
    return normalized.strip()


def _normalize_state(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip().lower()
    return value if value in WORKFLOW_STATES else ""


def _choose_slug(target_state: str, artifact_slug: str, inherited_slug: str, branch_name: str) -> str:
    if target_state in {PLAN, COOK, REVIEW} and artifact_slug:
        return artifact_slug
    if inherited_slug:
        return inherited_slug
    if target_state in {COOK, REVIEW}:
        return branch_slug(branch_name)
    return ""


def extract_artifacts(prompt: str = "", candidates: tuple[str, ...] | list[str] = ()) -> list[WorkflowArtifact]:
    paths: list[str] = []
    for value in candidates or ():
        if isinstance(value, str) and value.strip():
            paths.append(value.strip())
    paths.extend(_markdown_paths(prompt or ""))

    artifacts: list[WorkflowArtifact] = []
    seen: set[str] = set()
    for path in paths:
        cleaned = _clean_path_token(path)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        kind = artifact_kind(cleaned)
        if not kind:
            continue
        slug = slug_from_artifact_path(cleaned)
        if slug:
            artifacts.append(WorkflowArtifact(cleaned, kind, slug))
    return artifacts


def preferred_artifact_slug(artifacts: list[WorkflowArtifact]) -> str:
    for kind in ("prd", "plan"):
        for artifact in artifacts:
            if artifact.kind == kind:
                return artifact.slug
    return ""


def artifact_kind(path: str) -> str:
    lower = path.lower()
    parts = [part for part in re.split(r"[/\\]+", lower) if part]
    basename = parts[-1] if parts else lower
    stem = re.sub(r"\.(md|markdown)$", "", basename)
    if "prd" in parts or "prd" in stem:
        return "prd"
    if "plan" in parts or "plan" in stem or "plans" in parts:
        return "plan"
    return ""


def slug_from_artifact_path(path: str) -> str:
    basename = os.path.basename(path.strip())
    stem = re.sub(r"\.(md|markdown)$", "", basename, flags=re.IGNORECASE)
    return normalize_slug(stem)


def branch_slug(branch_name: str) -> str:
    value = normalize_slug(branch_name.split("/")[-1] if branch_name else "")
    return "" if value in _GENERIC_BRANCHES else value


def normalize_slug(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value


def _markdown_paths(text: str) -> list[str]:
    return [match.group(1) for match in re.finditer(r"(?:^|[\s`'\"(])([^\s`'\"()]+\.m(?:d|arkdown))(?=$|[\s`'\"),.])", text)]


def _clean_path_token(path: str) -> str:
    cleaned = path.strip().strip("`'\"()[],.")
    if _PLACEHOLDER_PATH_RE.search(cleaned):
        return ""
    return cleaned
