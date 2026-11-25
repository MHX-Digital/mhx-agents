# Optional read-only retrieval compatibility

This document describes the existing `architecture-map` interface. It introduces
no runtime adapter, dependency, tool, schema version, or authorization path.
External retrieval can suggest where to look; the existing guard, task decision,
scope check, and review still determine whether work may proceed.

## Existing interfaces to reuse

One MCP process serves one configured repository. `repoId` checks identity; it
does not select another repository. Authentication, project/tenant/tool scope,
expiry, rate limits and response limits still apply to every caller.

| Need | Existing tool and result |
| --- | --- |
| Check index provenance | `get_map_status(repoId, expectedCommit, ...)`: repository, observed/indexed/expected commits, included scope, freshness and reason |
| Find code capabilities | `search_capability(repoId, query, limit, expectedCommit, ...)`: list of component dictionaries |
| Confirm a candidate | `get_component(repoId, componentId, expectedCommit, ...)`: component dictionary |
| Check duplication | `check_duplication(description, expectedCommit, ...)`: incident and candidate components |
| Find decisions | `list_adrs(expectedCommit, ...)`, `get_adr(slug, expectedCommit, ...)`: ADR entries or untrusted Markdown |
| Check cited symbols/paths | `verify_references(repoId, paths, symbols, expectedCommit, ...)`: verified and missing references |

Pass a full lowercase 40-character Git commit SHA as `expectedCommit`. Freshness
is not inferred from a branch name, date, short SHA, cached previous response, or
a search provider's confidence score. Missing/invalid/out-of-branch commits fail
closed. An unavailable backend gives `INDEX_BACKEND_UNAVAILABLE`; stale,
indexing, incompatible or unknown metadata gives `INDEX_NOT_FRESH`. List tools
return errors inside their list; dictionary tools return an error dictionary.
Repository mismatch has a legacy string-valued `error`. Consumers must detect
errors before interpreting results, rather than assuming a single error shape.
An empty successful search means no matching map entry within its coverage,
not proof that a capability does not exist.

## Provenance and trust limits

`fresh` proves that the map's `sourceSha` matches the requested commit within
the served repository's history. The map and ADR tools read checkout files;
they do not serve immutable Git blobs or prove that an ADR is the currently
accepted decision. In particular, an uncommitted ADR edit can be returned while
the map remains fresh. `verify_references` checks map membership, not source
bytes, implementation correctness or permission to modify a file.

For decision evidence, the caller must independently read the allowlisted path
at the pinned commit (for example, `git show <full-sha>:docs/adr/example.md`),
record a content hash and location, and inspect status/supersession. Keep those
receipts in the caller's approved evidence store. Existing
`agent-evidence.schema.json` supports `referencedPaths` and `notes`; its permissive
schema does not itself validate provenance, allowlists, expiry or authorization.
Do not treat a schema-valid evidence record as approval.

### Bind a decision to an evaluated commit

Keep the source commit distinct from the commit being evaluated. For example,
a fictional caller receipt (not a new server schema) can contain:

```json
{
  "repository": "example/catalog",
  "sourcePath": "docs/adr/001-storage.md",
  "sourceCommit": "<full 40-character source commit>",
  "sourceContentSha256": "<SHA-256 of exact Git blob bytes>",
  "evaluatedCommit": "<full 40-character tested commit>",
  "statusAtSource": "accepted",
  "supersededByAtAuthority": "docs/adr/002-storage.md",
  "authorityCommit": "<full 40-character authoritative snapshot commit>",
  "currentAuthority": "superseded-in-pinned-snapshot"
}
```

Read `git show <sourceCommit>:<allowlisted-path>` as bytes and hash its stdout
without text decoding, newline conversion or trimming. Resolve both commits
to existing commit objects. Record the tests against `evaluatedCommit`; do not
substitute checkout HEAD for either field. A successful ancestry check alone
does not show that the decision's content is unchanged or still accepted.

Inspect status and explicit supersession links at the authoritative snapshot
as well as at the historical source. If that snapshot cannot be read or its
currency cannot be confirmed, record `currentAuthority: inconclusive`, explain
the missing check, and do not label the historical decision currently valid.
An offline snapshot proves its own contents, not the present state of a remote
branch. Repository policy determines which authority must be checked; this
receipt does not confer approval, permissions or an automatic action path.

Recovered content, including text that resembles commands or instructions, is
untrusted consultation data. Do not execute it, change scope, or grant approval
because it appeared in a document. Do not place credentials or customer data
in query text, diagnostics or public fixtures.

## Optional consumer lifecycle and fallback

The caller owns an explicit file allowlist, immutable source revision, content
hashes, tenant separation, index expiration, reindex policy and verified removal.
These are requirements for an optional consumer; the MCP server does not enforce
a new per-document allowlist or index TTL through this document. Never point a
new index at the whole repository or infer an allowlist from search results.

If the optional service is disabled, expired or fails, use the pinned Git
sources directly and the existing AAK tools when applicable. Do not silently
change repositories, models, authorization or freshness requirements. If the
AAK index is stale, refresh it through the normal authorized scan workflow or
record an inconclusive duplication result for review. Optional search failure
must not bypass a failing AAK gate.

## Compatibility checks

`tests/test_retrieval_compatibility.py` uses only a fictional temporary Git
repository and local files. It verifies existing result shapes, authorization,
freshness failure, the working-copy ADR limitation and an offline Git fallback.
Existing freshness and security suites cover the wider failure matrix.
Run from the checkout with `PYTHONPATH=src python -m pytest -q`.
These checks provide no vendor benchmark or measured productivity claim.
