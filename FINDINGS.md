# Capability findings and limits

This public source preview is validated with fictional repositories and fixtures.
The source tree, test suite and CI receipts are the evidence; a historical client
session is not a guarantee of behavior in every coding environment.

| Capability | Evidence | Limit |
|---|---|---|
| Tool payload normalization and scope denial | tests/test_guard_bypass.py | Requires correctly installed client wiring; not an OS sandbox |
| Decision expiry, branch and ancestry checks | tests/test_decision.py | Protected state and operator authorization remain separate |
| Map freshness and exact source revision | tests/test_mcp_freshness.py | Map coverage does not prove decision authority |
| Tenant/project/tool authorization and redaction | tests/test_mcp_security.py | Local HMAC is not production identity management |
| Atomic publication and rollback | tests/test_index_lifecycle.py | Local filesystem coordination, not distributed locking |
| Synthetic duplicate correlation | tests/test_duplication_golden_corpus.py | Fictional examples, not client shadow calibration |
| Installed wheel and sdist | scripts/ci/check_distributions.py | Supported interpreter matrix is checked in CI |

Advisory hooks provide context. Pre-tool/post-tool enforcement only applies to
requests routed through the configured adapters. A writable local directory is
not an authorization boundary. Retain the coding client's default permission
checks and use a separate operator-reviewed scope before execution.

No production deployment, private project, remote identity, monthly availability,
or time-saving claim follows from these fixtures. See the issue-resolution map
for implementation evidence and proposed residual work.
