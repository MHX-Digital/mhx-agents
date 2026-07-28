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
aak scan run --repo-root <path> --language <typescript|python> [--check]
aak portfolio scan --root <path> [--json]
```

## with-build-lock.sh

`bin/with-build-lock.sh [--timeout SECONDS] [--lock-name NAME] -- <command> [args...]`

flock-based semaphore so heavy commands (`npm ci`, `docker build`, `npm run
build`) don't run concurrently and starve each other on a resource-constrained
host. Motivated by a real incident (2026-07-28): several PRs' CI jobs queued
up on the same single self-hosted runner and ran serially, much slower than
expected. Wrap heavy manual commands with it, e.g.:

```
bin/with-build-lock.sh --lock-name docker -- docker build -t myimage .
```

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

This is the Phase 1 slice only: `project`/`task-decision`/`agent-evidence`
schemas, one guard with three adapters, keyword-based protected-domain
matching. No CI integration for the guard itself, no shadow-mode calibration
yet - see the master plan's rollout tracks for what comes after the pilot
proves out.
