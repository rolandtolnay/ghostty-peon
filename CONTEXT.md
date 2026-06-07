# Ghostty Peon

Ghostty Peon names Ghostty tabs and plays Warcraft III-themed sounds for assistant sessions. This context captures the language for tab-title workflow behavior.

## Language

**Ordinary Pi Session**:
A Pi session whose tab title behavior follows the existing opportunistic title-generation flow.
_Avoid_: non-workflow session, default session

**Canonical Workflow Mode**:
A Pi-only tab-title mode entered when a session matches a known workflow signal.
_Avoid_: global workflow mode, Claude workflow mode

**Workstream**:
An independent piece of work the user tracks through one or more Pi sessions, usually represented by one Ghostty tab.
_Avoid_: project, session, branch

**Workflow State**:
The visible phase prefix of a canonical workflow title.
_Avoid_: status, command name

**Task Slug**:
The dash-separated name that identifies the piece of work across workflow states and sessions.
_Avoid_: title, summary, branch name

**Canonical Slug**:
The task slug selected from an existing workflow artifact.
_Avoid_: LLM slug, generated title

**Workflow Artifact**:
A PRD or plan file whose path or filename identifies a workstream.
_Avoid_: transcript, conversation context

**Check**:
The workflow state for an initial prompt that a transition judgment classifies as a sanity-check or ticket-oriented workstream.
_Avoid_: inspect, triage

**Prep**:
The workflow state for producing shared product understanding before planning.
_Avoid_: prepare, specification

**Plan**:
The workflow state for turning a PRD or task into an implementation plan.
_Avoid_: design, strategy

**Cook**:
The workflow state for implementing an existing plan.
_Avoid_: implement, execute

**Review**:
The workflow state for reviewing completed or in-progress implementation work.
_Avoid_: audit, critique

**Implementation Handoff**:
A user prompt that asks to implement the current plan without invoking an explicit cook command.
_Avoid_: generic implementation request, kickoff

**Transition Judgment**:
A local-LLM classification of whether an ambiguous user prompt should move a canonical workstream to another workflow state.
_Avoid_: keyword match, magic phrase

## Relationships

- A **Canonical Workflow Mode** session belongs to one **Workstream**.
- A **Workstream** has exactly one current **Workflow State**: **Check**, **Prep**, **Plan**, **Cook**, or **Review**.
- A **Workflow State** title includes one **Task Slug**.
- A **Canonical Slug** replaces opportunistic title slugging only when a **Workflow Artifact** already exists.
- A **Workflow Artifact** can attach the current tab to an existing **Workstream**.
- An **Implementation Handoff** moves a **Workstream** from **Plan** to **Cook** only when a **Transition Judgment** says the user intends to implement the current plan.
- Deterministic workflow signals change **Workflow State** without a **Transition Judgment**.
- First-turn **Check** entry is decided by **Transition Judgment**, not by hardcoded prompt phrases.
- An **Ordinary Pi Session** does not become canonical unless it matches a known workflow signal.

## Example dialogue

> **Dev:** "If the first Pi prompt says `sanity check MIN-180`, is this an ordinary title?"
> **Domain expert:** "No — that enters **Canonical Workflow Mode** for that **Workstream** in the **Check** state, but its **Task Slug** still comes from the existing opportunistic generator until a later state references an existing **Workflow Artifact**."

## Flagged ambiguities

- "workflow session" could mean any Pi session on a feature branch; resolved: only a session with a known workflow signal enters **Canonical Workflow Mode**.
- "project" and "branch" were considered as workstream identities; resolved: neither is unique enough because multiple **Workstreams** can run in the same project, on the same branch, or in separate worktrees.
- Ambiguous transition prompts such as implementation handoffs should not be recognized by hardcoded magic phrases; resolved: use **Transition Judgment** with state-specific local-LLM prompts.
- First-turn ticket and sanity-check prompts were initially considered deterministic **Check** signals; resolved: classify them with **Transition Judgment** so prompt wording does not become a hidden API.
