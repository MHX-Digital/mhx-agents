# Main governance proposal — not applied

Use main as the default PR base. Maintain at most one active work branch and one
registered worktree for this public checkout; preserve unrelated private Git
groups and active work. No repository deletion, extra cleanup or release is
authorized merely by this proposal.

Proposed required GitHub Actions checks (app ID 15368):

- `Python 3.10`
- `Python 3.12`
- `Dependency audit`

Require an up-to-date base, resolved review conversations, one independent human
approval and dismissal of stale approvals. Disable force pushes and deletion of
main; keep merge commits available for traceability. Apply the rule to admins
only after a second eligible human reviewer is available; otherwise a sole
maintainer cannot satisfy independent approval. Agents and MCP tools do not
provide approval.

The consumer architecture-gate file is a template, not an active check in this
repository. Do not require its job names before a real workflow emits them.
CI includes PR, main push and manual events; a base/head change requires fresh
checks. Merge, issue closure, administrative rules, tags and release publication
remain maintainer decisions, separate from this PR.
