# ADR-0001: Atomic and recoverable local index publication

Status: implementation documented; release and operational approval are separate.
Related public changes: [#32](https://github.com/MHX-Digital/mhx-agents/pull/32),
[#36](https://github.com/MHX-Digital/mhx-agents/pull/36).

## Design

The scanner defines the content. IndexLifecycle builds from an isolated Git
revision, validates schema/repository/commit/checksums, serializes publishers,
checks the previous active bytes, snapshots them and promotes via os.replace.
Requested, indexing, validating, ready, publishing and published states distinguish
in-progress work from an active result. Failed/cancelled candidates do not replace
the last valid index. Rollback verifies snapshot identity and checksum first.

The requested commit must be an existing ancestor of the selected branch. State
and active-index paths are constrained to the configured repository. Only owned
temporary worktrees are removed. Audit records contain metadata, not index bytes.

## Limits and evidence

Atomic replacement requires an adjacent temporary file on the same filesystem.
Local exclusive locks do not provide cross-host coordination. Retention is an
operator policy; failed candidates are preserved for investigation.
tests/test_index_lifecycle.py and tests/test_mcp_integrated_resilience.py cover
synthetic interruption, concurrency, publication and rollback. No client or
production rollout is asserted by this ADR.
