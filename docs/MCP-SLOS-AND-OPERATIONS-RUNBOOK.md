# Read-only MCP: proposed operational gates

This is a public operational proposal. Unit fixtures and a short CI canary are
not a production measurement series or a contractual SLO.

## Current evidence

tests/test_mcp_integrated_resilience.py covers synthetic concurrency, publication,
rollback and isolation. scripts/ci/smoke_readonly_mcp.py starts the actual stdio
server against a disposable fictional Git project, calls all seven tools and
checks denied requests. Receipts identify the checked code and fixture commits.

## Before a live rollout

Define the operator, reviewer, environment, exact source commit, project/tenant,
resource/time budget, data allowlist, auth issuer, retention and rollback path.
Back up and verify the prior index; observe freshness, errors, CPU/RAM/disk and
latency for a reviewed window. Never infer production availability or percentiles
from one CI invocation. Remote transport requires its own identity/TLS review.

## Stop and recover

Stop on a repo/tenant/checksum/schema mismatch, unauthorized response, unredacted
credential, stale conclusive result or failed rollback. Preserve metadata and the
failed candidate. Revoke the test identity, stop only the owned process, restore
the verified prior snapshot, check freshness, and keep direct Git navigation as
fallback. Do not purge shared caches or unrelated services.

The CI fixture removes only its owned project/process and records cleanup.
Monthly availability, human RTO, sustained capacity and real-client shadow
calibration remain open work, not completed checklist items.
