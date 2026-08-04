# Skill-aware titles are stateless

Ghostty Peon uses the ordinary opportunistic title generator for every Claude Code and Pi prompt. An explicit skill invocation is evaluated as a fresh title request using its user request and a bounded opening description; `scope` or `prep` may add its name to the newly generated slug, but the prefix has no persisted identity and does not cause later transitions.

This supersedes ADR 0001. Durable workstreams, inferred workflow phases, artifact attachment, branch fallback, and transition-specific model calls created more failure modes than useful title information. Session lifecycle handoffs continue to preserve visible titles, while PRD paths, plans, branches, and transcript history no longer control title identity.
