# agent-architecture-kit

Phase 1 implementation of the anti-duplication multi-agent mechanism described
in `MHX-MULTI-AGENT-ARCHITECTURE-FINAL-2026-07-27.md`, scoped to the LexNotify
pilot on VPS `mhx-lab`. See `FINDINGS.md` for the real, tested capability
findings this kit's guard logic relies on.

## Commands

```
aak doctor
aak guard pretool --client <claude|codex>          # reads PreToolUse JSON on stdin (gemini not implemented, see Scope note)
aak guard posttool --client <claude|codex>
aak guard precommit
aak task start --executor <client> --issue <n> --allow-existing <path>... --allow-new <path>...
aak task status
aak override create --issue <n> --scope <glob> --reason <text> --expires <iso8601>   # run from inside the target repo
aak scan run --repo-root <path> --language <typescript|python> [--check]
aak portfolio scan <root>
aak mcp serve --repo-root <path>                   # architecture-map MCP server (stdio)
aak verify [--language <typescript|python>] --staged   # unified gate: manifest/map schema + drift + scope; see ci/github/architecture-gate.yml
```

## MCP server: `architecture-map`

`aak mcp serve --repo-root <path>` starts a read-only, single-repo MCP server exposing
`search_capability`, `get_component`, `check_duplication`, `list_adrs`, `get_adr`,
`get_map_status`, `verify_references` (master plan section 7.1; `find_similar` and
`get_impact_graph` are not implemented yet -- they need import-edge extraction the scanner
doesn't produce). Wire it via `.mcp.json` (see `templates/repository/.mcp.example.json`); the
`map-guardian` subagent (`templates/repository/.claude/agents/map-guardian.md.template`) is the
intended consumer.

## Reusing this kit in a new repo

`templates/` is the canonical starting point for onboarding a new Tier 1/2 repo (master plan
section 8.1/8.2) -- copy, fill in the `<PLACEHOLDER>` markers, and drop the `.template` suffix:

```
templates/
├── github/            # ISSUE_TEMPLATE/*.yml, PULL_REQUEST_TEMPLATE.md, labels.yml
├── repository/         # AGENTS.md, CLAUDE.md, .agent-architecture/project.yaml,
│                        # .claude/settings.json (hooks), .claude/agents/map-guardian.md,
│                        # .mcp.example.json
└── adr/ADR-TEMPLATE.md
```

`labels.yml` uses the canonical English `verdict:*` names (`new`/`extend`/`duplicate`/
`inconclusive`). LexNotify-Web's first rollout (2026-07-28) used Portuguese names
(`verdict:novo`/etc) before this template existed -- that repo's labels were left as-is rather
than renamed under active use; any new repo should start from this canonical set.

## Setup

```
python3 -m venv .venv
.venv/bin/pip install -e .          # editable install, exposes the aak console script
.venv/bin/pip install -e '.[dev]'   # + pytest, for running tests/
```

`bin/aak` is a thin wrapper around `.venv/bin/aak` kept at this exact path
because every consumer repo's `.claude/settings.json`/`~/.codex/config.toml`
hardcodes it as the hook command.

State (protected task decisions, locks) lives outside this repo, at
`/srv/agent-architecture/state/` by default (override with `AAK_STATE_ROOT`).

## Scope note

This is the Phase 1 slice only: `project`/`task-decision`/`agent-evidence`/`architecture-map`/
`override` schemas, one guard with two adapters (claude/codex -- Gemini was deliberately
descoped, see `orchestrate.py`/`doctor.py`), keyword-based protected-domain matching. No
shadow-mode calibration yet, no golden duplication corpus, no scanners beyond TypeScript/Python -
see the master plan's rollout tracks for what comes after the pilot proves out.
