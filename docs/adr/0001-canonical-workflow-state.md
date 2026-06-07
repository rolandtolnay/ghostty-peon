# Canonical workflow state is workstream-scoped

Ghostty Peon stores Pi canonical workflow state in Ghostty Peon home state and reuses it only after explicit workflow signals or artifact references. State is scoped to the user’s workstream, with artifact slugs becoming durable attachment points, because multiple independent workstreams can run in the same project, on the same branch, or in separate worktrees; project-scoped, branch-scoped, or always-restored state would hijack ordinary Pi sessions or collapse distinct tabs into one workflow.
