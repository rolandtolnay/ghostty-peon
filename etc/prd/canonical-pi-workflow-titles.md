## Problem Statement

Ghostty Peon’s current Pi tab titles are driven by opportunistic local-LLM slug generation. That works for ordinary chats, but it loses useful structure when a piece of work moves through the Pi workflow states of check, prep, plan, cook, and review. The user often runs several workstreams at once, including multiple workstreams in the same project and even on the same branch, so project-, branch-, or session-only title state cannot reliably identify the work at a glance.

## Solution

Add a Pi-only canonical workflow title mode that preserves existing Claude behavior and ordinary Pi behavior. When a Pi session enters a known workstream, Ghostty Peon shows a state-prefixed title such as `check-<slug>`, `prep-<slug>`, `plan-<slug>`, `cook-<slug>`, or `review-<slug>`. Structural workflow signals are handled deterministically, while semantic user-intent transitions are judged by the local LLM with state-specific prompts rather than fragile keyword lists.

## User Stories

1. As a Pi user, I want canonical workflow tabs to show the current workflow state, so that I can identify whether a workstream is in check, prep, plan, cook, or review.
2. As a Pi user, I want ordinary Pi sessions to keep today’s opportunistic title behavior, so that casual question tabs do not become workflow tabs by accident.
3. As a Claude Code user, I want Claude tab titles to behave exactly as they do today, so that Pi workflow changes do not regress the Claude integration.
4. As a user running parallel workstreams, I want workflow state to follow a workstream rather than a project or branch, so that multiple tabs in the same project can remain distinct.
5. As a user starting from a check or prep conversation, I want the early task slug to come from the existing local-LLM slugging behavior, so that early titles still work before a PRD or plan exists.
6. As a user moving into planning, cooking, or review from an existing artifact, I want the artifact slug to become the canonical slug, so that follow-up sessions use the stronger slug already chosen for the work.
7. As a user continuing work in a different tab, I want referencing a PRD or plan artifact to attach that tab to the existing workstream, so that the same work can continue outside its original tab.
8. As a user giving semantic follow-up instructions like moving from a plan into implementation, I want Ghostty Peon to use local-LLM transition judgment rather than hardcoded magic phrases, so that natural wording still works.
9. As a user invoking `/cook-plan`, I want the tab title and title sound to update once for the cook handoff, so that duplicate title generation and duplicate acknowledgement behavior do not occur.
10. As a user on feature branches or worktrees, I want branch names to help recover cook/review slugs only when stronger inherited or artifact slugs are unavailable, so that branches help without overriding the workstream identity.

## Implementation Decisions

- Canonical workflow behavior is Pi-only and additive. Shared hook code may be reused, but canonical behavior must be gated so Claude and ordinary Pi sessions preserve current behavior.
- The visible canonical workflow states are exactly `check`, `prep`, `plan`, `cook`, and `review`. Variants collapse into those states rather than appearing as separate prefixes.
- Deterministic workflow signals enter or update canonical workflow mode without a local-LLM transition judgment:
  - `prep` and `to-prd` map to `prep`.
  - `plan` and `plan-quick` map to `plan`.
  - `cook-plan`, the cook skill, and clear plan-implementation kickoffs map to `cook` when they carry structural plan context.
  - `review`, `review-hard`, `triage-pr-comments`, and `review-nuclear` map to `review`.
- Semantic prompt intent uses local-LLM transition judgment with state-specific prompt bundles, not hardcoded keyword allowlists.
- Initial `check` entry is classified by the local LLM on the first user turn. If classification is uncertain, invalid, or times out, the session remains ordinary.
- The initial transition judgments in scope are first-turn ordinary-to-check, check-to-prep, and plan-to-cook.
- Transition judgments receive current workflow state, current title, current prompt, title origin, and recent transcript context. They should return a constrained decision, not a slug.
- When a transition judgment is uncertain, invalid, or times out, existing canonical workstreams keep their current state/title and non-canonical sessions remain ordinary.
- Check and prep titles always include the workflow prefix, but their slugs continue to come from the existing opportunistic slug generator until an existing artifact is referenced later.
- Artifact slug extraction prefers PRD slugs over plan slugs when both are visible. Artifact references can attach the current tab to an existing workstream.
- Slug priority is state-specific:
  - Check and prep use inherited/opportunistic slugs.
  - Plan prefers an existing PRD artifact slug, then inherited/opportunistic slug.
  - Cook and review prefer artifact slug, then inherited slug, then non-generic feature branch slug.
- Feature branches are slug hints, not workstream identity. Generic branches such as main/develop/trunk-like names are ignored.
- Canonical state persists in Ghostty Peon home state, separate from the existing debounce file format. Existing debounce and short-lived session handoff behavior should not be overloaded for durable workstream state.
- Persisted canonical state is signal-gated: it is reused only when a canonical signal or artifact reference appears. Ordinary prompts must not automatically restore stale workflow state.
- A new check or prep signal in an existing canonical tab replaces the tab’s current workstream unless an artifact reference attaches it to an existing artifact-backed workstream.
- Ordinary follow-up prompts inside canonical workflow mode keep the current workflow title unless a deterministic workflow signal or local-LLM transition judgment changes state.
- Canonical title changes play the existing task acknowledgement sound when the visible state or slug changes. Ordinary canonical follow-ups do not play a title-change sound.
- Cook-plan integration should provide enough structured plan metadata for Ghostty Peon to seed `cook-<slug>` once and suppress a second opportunistic title-generation path for the kickoff prompt.
- The durable workstream identity/storage decision is recorded in an ADR because project-scoped or branch-scoped state is an attractive but incorrect simplification for this workflow.

## Testing Decisions

- Tests should assert observable title decisions and state transitions rather than internal cache mechanics.
- The workflow model should be tested as a deep module: given runtime signals, current workflow state, artifact context, branch context, and transition judgment results, it returns the expected title action.
- The transition-judgment layer should be tested for strict parsing of local-LLM output, including uncertain, invalid, and timeout cases that keep state unchanged.
- The durable workstream state should be tested for tab/workstream persistence, artifact attachment, signal-gated reuse, and multiple workstreams in the same project.
- Pi event mapping should be tested for selected skill metadata and command/metadata propagation needed by canonical signals.
- Hook-level tests should cover canonical check/prep/plan/cook/review transitions, ordinary Pi fallback behavior, and Claude behavior remaining unchanged.
- Cook-plan regression coverage should prove that a cook handoff produces one canonical title update path and does not trigger duplicate kickoff title generation/sound.
- Existing prior art includes hook-level Python tests for debounce/title state, Pi lifecycle handoff, slug validation, and Node-based Pi event mapping tests.

## Out of Scope

- Replacing the existing opportunistic slug generator for ordinary Pi sessions.
- Changing Claude Code title behavior.
- Watching prep file writes to immediately rename the prep tab when a PRD is created.
- Building a broad speculative workflow framework beyond the five current states.
- Creating interactive prompts from hooks when state attachment or replacement is ambiguous.
- Solving all possible semantic transitions in the first version; only first-turn check, check-to-prep, and plan-to-cook transition judgments are included.
- Treating project path or branch name as the primary workstream identity.

## Further Notes

- This PRD covers MIN-180 and should also address the related cook-plan duplicate-trigger issue from MIN-179.
- The implementation should preserve the current debounce file contract and avoid changing shared hook behavior unless gated to Pi canonical workflow mode.
- Manual verification should include ordinary Claude, ordinary Pi, and canonical Pi workflow sessions in Ghostty.
