# ADR-0002: Deny-by-default read-only MCP boundary

Status: local implementation documented; remote identity and rollout pending.
Related public change: [#37](https://github.com/MHX-Digital/mhx-agents/pull/37).

## Contract

Authenticate, authorize the exact project/tenant/tool, validate input, verify
freshness, read allowed context, redact/limit responses and audit metadata.
Possession of a repository or tenant name is not authorization. Fictional tenant
tenant-example cannot read a different tenant's context.

The local issuer uses HMAC-SHA256 with key ID, expiry, revocation and explicit tool
allowlists. Keys are supplied through the environment; real keys are never part
of fixtures. Production identity integration is external. All roles remain
read-only: no shell, mutation or arbitrary filesystem tool is exposed.

ADR slugs are validated and resolved within the configured ADR directory; symlink
escapes fail. Retrieved content is labeled untrusted consultation data, never
instructions or approval. Redaction covers common credential forms and personal
paths. Rate and response-size limits fail closed. Events contain request metadata
rather than tokens or retrieved content.

## Evidence and remaining work

tests/test_mcp_security.py covers missing/invalid/expired/revoked credentials,
tenant/project/tool isolation, path traversal, injection labeling and redaction.
The CI stdio canary exercises the real local transport with fictional data.
TLS, multi-host identity, durable shared limits, production retention and live
rollout require separately approved work. A stdio canary does not prove them.
