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


def deterministic_state(selected_skills: tuple[str, ...] | list[str]) -> str:
    for skill in selected_skills or ():
        normalized = _normalize_skill(skill)
        if normalized in _SKILL_STATE:
            return _SKILL_STATE[normalized]
    return ""


def _normalize_skill(skill: object) -> str:
    if not isinstance(skill, str):
        return ""
    return skill.strip().lstrip("/").lower()


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
    return path.strip().strip("`'\"()[],.")
