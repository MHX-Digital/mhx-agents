# MHX Agents — first source and package preview

Local/public review draft only. No tag, release or new version is selected by
this document. Review version/tag alignment before publication: the distribution
remains `agent-architecture-kit` version `1.0.0+phase1`, with CLI `aak` reporting
`1.0.0-phase1`.

## Highlights

- English onboarding with a reproducible fictional project and an agent-control
  architecture overview.
- Seven runtime schemas bundled in wheel and sdist, with resource lookup that
  works outside a source checkout.
- Claude Code and Codex guard adapters, scoped decisions, architecture scanning
  and the read-only architecture-map MCP interface.
- Fictional public fixtures that preserve correlation, freshness and security
  assertions without exposing a private project or tenant.
- Python 3.10/3.12 CI, isolated distribution checks, real stdio smoke checks and
  reproducible whitespace rejection canaries.
- Secure MCP 1.x dependency floor; package name, import namespace and CLI retained.

## Review before release

Confirm the approved commit, three green checks and installed artifact receipts.
Link release documentation and test evidence to that commit. Do not label a
synthetic canary as production validation or assume that client hooks were
activated. Choose the release tag and publish artifacts only after approval.

Start with the [README](../README.md), [retrieval contract](READ_ONLY_RETRIEVAL.md),
[issue map](ISSUE_RESOLUTION_MAP.md), and [governance proposal](GOVERNANCE_PROPOSAL.md).
These links are source-relative; use approved commit-pinned URLs in a final
GitHub release body.
