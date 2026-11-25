# Public backlog and CI resolution map

Related: [#20](https://github.com/MHX-Digital/mhx-agents/issues/20) and
[#39](https://github.com/MHX-Digital/mhx-agents/issues/39). This document proposes
scope and closure decisions; it does not close either issue or approve a release.

## Issue #20: July backlog reconciled with public source

“Main” below means the baseline before this PR. “PR” means proposed changes that
are not in main until reviewed and merged. CI receipts record the actual checked
commit; an implementation file alone is not operational evidence.

| Original item | Main / PR evidence | Remaining decision or proof |
|---|---|---|
| Generic kit skeleton | Main: src/aak, CLI | Delivered source capability |
| Project/map/evidence/decision/override schemas | Main: schemas, test_schemas | PR packages all seven; test_package_schemas and check_distributions |
| Protected locks and decisions | Main: decision.py; PR: malformed-expiry regression | Cross-worktree overlap remains open |
| Independent brief/audit/reconciliation | Main: single Codex planner | Independent second review is not implemented; alternate providers need a scope decision |
| Lifecycle adapters and feature intake | Main: hooks.py | Hooks are advisory; mandatory feature-intake procedure remains open |
| Client pre-tool guard adapters | Main: adapters, test_guard_bypass | Client wiring must be verified per project; only Claude/Codex supported |
| Shell-write/post-tool scope | Main: guard.py, bypass corpus | Not an OS sandbox; permissions must remain enabled |
| Deterministic scanner interface | Main: scan/core.py | Delivered source capability |
| Language adapters | Main: TypeScript/Python/Rust/Solidity/Dart, test_scan_adapters | SQL/Supabase and deeper semantic coverage remain open |
| Read-only architecture-map MCP | Main: seven tools and security/freshness tests | PR runs an actual stdio synthetic canary; impact graph/import edges remain open |
| Shared instruction/intake templates | Main: templates | PR removes host-specific paths; onboarding still requires operator review |
| Incident feedback and Map Brief evaluation | Main: duplicate correlation | PR uses fictional replay data; ongoing reviewed alias/threshold feedback remains open |
| Heavy-task semaphore and bounded runner | Main: with-build-lock.sh; bounded subprocess calls | Global integrated allowlist/attempt-cap runner remains open |
| Deterministic architecture gate | Main: reusable template | PR corrects consumption docs; actual consumer enforcement remains project-specific |
| Read-only independent review job | Main: schema only | No independent review workflow is delivered |
| Duplication golden corpus | Main: correlation/replay mechanics | Public PR preserves five assertions using fictional incidents; no client data or real-world coverage claim |
| Shadow calibration | No production time series | Requires a separately approved observation window |
| Tier-1 consumer enforcement | No universal deployment proof | Requires target project/client receipts, scope and rollback |
| Portfolio scoring and index outputs | Main: portfolio scanner | Curated exports/index files and freshness ownership remain open |
| Provision/harden a host | Historical operational item | Proposed out of scope for this generic public package; not re-audited |
| Mount a curated document corpus | Optional source helper only | Operator credentials and data policy are external; no corpus was read here |
| Repair a client's agent catalog | Historical client-specific item | Proposed out of scope; public package is not a hosted agent library |

Recommendation: **keep #20 open**. The completed primitives do not satisfy all
remaining workflow, scope and operational items. Maintainers should approve the
public scope explicitly rather than silently checking off historical host work.

### Proposed follow-up issues (not created automatically)

1. **Define independent review and intake contracts.** Specify reviewer independence,
   evidence/handoff fields and failure behavior; test without changing models or
   treating a plan as human approval.
2. **Detect cross-worktree scope overlap.** Define lock ownership, bounded leases,
   recovery and concurrent conflict tests before expanding the decision model.
3. **Add SQL/Supabase and dependency-edge coverage.** Document extraction coverage;
   use fictional fixtures and explicit false-negative/false-positive cases.
4. **Implement reviewed incident-feedback evaluation.** Version aliases/thresholds
   through PRs and replay held-out synthetic cases; never capture sessions silently.
5. **Define a bounded heavy-task runner.** Compose concurrency, deadlines, per-operation
   retries and allowlists; prove cancellation and uncertain-effect reconciliation.
6. **Run project onboarding and shadow calibration.** Select an approved project,
   reviewed data scope, observation window, client wiring and rollback; record
   operational results separately from CI fixtures.
7. **Publish curated portfolio index outputs.** Define source ownership, allowlists,
   freshness and removal; do not inventory unrelated directories automatically.
8. **Specify remote identity and durable shared operations.** Address TLS, retention,
   distributed limits and human recovery before any remote production service.

## Issue #39: CI acceptance

| Original criterion | Evidence in this PR |
|---|---|
| Workflow parses and runs on a PR | .github/workflows/mcp-release-gates.yml; public Actions run linked from the PR |
| A real failure stops the gate | check_whitespace.py + test_whitespace_gate.py; manual opt-in failure_canary.py propagates nonzero from fictional whitespace and pytest failures |
| At least 119 tests | Full suite/JUnit on Python 3.10 and 3.12; exact count is in each run |
| Critical suites run explicitly | freshness, lifecycle, security and integrated-resilience steps |
| Permissions and timeout bounds | contents:read, SHA-pinned actions, no PR secrets/cache, job deadlines, cancellation and test_ci_contract.py |
| Dependency and secret checks | Dependency audit job, aggregate secret scan, short-retention SBOM/JUnit receipts |
| Checks green on submitted SHA | Verify the three checks on the PR head; do not reuse an older main or a historical run |
| Limits / protection pending documented | GOVERNANCE_PROPOSAL.md; stdio fixture limits below |

The whitespace gate checks a real PR base-to-HEAD diff, the last commit for a
manual run, and the initial commit for a root history. Invalid/missing bases
fail. Tests reject bad diffs and accept a corrected final diff despite a bad
intermediate commit. This avoids both the empty-base no-op and historical-log
false positives.

### Controlled canaries

The normal job starts an installed MCP server over stdio in a disposable fictional
project. It invokes all seven tools, checks auth/tenant/project/freshness/path
denials and removes the process and fixture. No model, paid provider, public
port, real credential or private corpus is used.

A maintainer can dispatch the same workflow with `canary_failure=true` to verify
an intentionally red job. Both a bad-whitespace Git fixture and a failing pytest
fixture are created only in a temporary directory. Their nonzero exits propagate
to the job. Normal PR/main runs default to false; no failing product commit or
change destined for main is created. Re-run without that input to restore a green
validation record on the same source SHA.

These canaries do not prove production SLOs, client-agent behavior, cross-host
identity or remote deployment. Administrative protection is a separate decision.

Recommendation: once all three current checks and the controlled failure receipt
are verified, **#39 is ready for closure after this PR is merged**, for its CI
implementation scope. Until then keep it open. Any production rollout remains
separate; do not close the broader #20 backlog because this CI issue is satisfied.
