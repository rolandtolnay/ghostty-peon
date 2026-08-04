# Ghostty Peon

Ghostty Peon names Ghostty tabs and plays Warcraft III-themed sounds for assistant sessions.

## Language

**Task Slug**:
A lowercase, hyphenated label generated from the user-authored task so a session can be found at a glance.
_Avoid_: workflow identity, branch name

**Opportunistic Title**:
A tab title that the local model may update when the conversation clearly changes topic.
_Avoid_: canonical title, workflow title

**Skill Prefix**:
The optional `scope-` or `prep-` label added when that skill is explicitly invoked for the prompt that generates a new task slug.
_Avoid_: workflow state, inferred phase

**Title Origin**:
The bounded prompt context that established the current task slug and helps the model judge later topic changes.
_Avoid_: full skill body, transcript

**Status Emoji**:
The leading symbol that reports whether the session is working, ready, waiting for input, or awaiting permission.
_Avoid_: workflow state

## Relationships

- Every substantive prompt follows the same opportunistic title-generation path in Claude Code and Pi.
- A session without a title asks only for a task slug; `KEEP` is valid only when an established title exists.
- A **Skill Prefix** is derived only from the current explicit skill invocation. It is not persisted separately or inferred from conversation history.
- Skill envelopes contribute their `<user-request>` plus at most the first three instruction blocks and 600 characters to title generation.
- Explicit skill invocation requests a fresh title even during the normal rename cooldown; an empty `<user-request>` can be titled from the bounded skill description.
- A **Title Origin** and recent user messages help distinguish continuation from a topic change.
- Session replacement handoffs preserve the visible title but do not attach durable task or workflow identity.
- **Status Emoji** changes are independent of task slug generation.

## Flagged ambiguities

- A title beginning with `scope-` or `prep-` is presentation, not durable workflow state.
- Plan acceptance in Claude Code is a session-lifecycle handoff and is unrelated to skill title prefixes.
- PRD paths, plan paths, branches, and historical transcript content do not control title identity.
