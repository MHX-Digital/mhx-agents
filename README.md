# agent-architecture-kit

Phase 1 implementation of the anti-duplication multi-agent mechanism described
in `MHX-MULTI-AGENT-ARCHITECTURE-FINAL-2026-07-27.md`, scoped to the LexNotify
pilot on VPS `mhx-lab`. See `FINDINGS.md` for the real, tested capability
findings this kit's guard logic relies on.

## Commands

```
aak doctor
aak guard pretool --client <claude|codex|gemini>   # reads PreToolUse JSON on stdin
aak task start --executor <client> --issue <n> --allow-existing <path>... --allow-new <path>...
aak task status
```

## Setup

```
python3 -m venv .venv
.venv/bin/pip install pyyaml jsonschema
```

State (protected task decisions, locks) lives outside this repo, at
`/srv/agent-architecture/state/` by default (override with `AAK_STATE_ROOT`).

## Scope note

This is the Phase 1 slice only: `project`/`task-decision`/`agent-evidence`
schemas, one guard with three adapters, keyword-based protected-domain
matching. No MCP, no CI, no multi-language scanners, no override workflow,
no shadow mode yet - see the master plan's rollout tracks for what comes
after the pilot proves out.
