# Capability findings (Phase 1, verified 2026-07-27 on a single production VPS)

These were tested live, not assumed from vendor docs, per the master plan's
instruction to verify capability before building the guard on top of it.

## Claude Code (v2.1.220)

- Auto-imports `AGENTS.md` from the project root into context without being
  asked to read it explicitly.
- A `PreToolUse` hook that exits `2` blocks the write, and the `stderr`
  message reaches the agent verbatim ("A hook is blocking file writes...").
- `PreToolUse` payload shapes (captured from a real hook invocation):
  - `Write`: `{"tool_name": "Write", "tool_input": {"file_path", "content"}}`
  - `Edit`: `{"tool_name": "Edit", "tool_input": {"file_path", "old_string", "new_string", "replace_all"}}`
  - `Bash`: `{"tool_name": "Bash", "tool_input": {"command", "description"}}`
- A directory must be marked trusted (`hasTrustDialogAccepted` in
  `~/.claude.json`, or accept the interactive trust dialog once) before
  `permissions.allow` entries in `.claude/settings.json` take effect. The
  hook itself still fires and blocks even in an untrusted directory.

## Codex CLI (v0.145.0)

- `PreToolUse` hooks are a stable feature (`codex features list` shows
  `hooks stable true`), but a hook that is new or changed is **not** run
  until a human trusts it once via the interactive TUI ("Hooks need review"
  prompt: Review / Trust all and continue / Continue without trusting).
  Running `codex exec` (headless) against an untrusted hook silently skips
  it with no error - this looks like "the hook didn't fire" if you only test
  headless.
- Once trusted, the decision persists in `~/.codex/config.toml` under
  `[hooks.state]` as a sha256 hash of the hook definition, and from then on
  the hook fires in both interactive and headless (`codex exec`) modes.
- `PreToolUse` payload shapes (captured from a real hook invocation):
  - `apply_patch`: `{"tool_name": "apply_patch", "tool_input": {"command": "*** Begin Patch\n*** Add File: <path>\n...*** End Patch\n"}}`
    (the target path must be regex-extracted from the patch text)
  - `Bash`: `{"tool_name": "Bash", "tool_input": {"command"}}`
- Sandbox (`-s workspace-write`) uses a bundled `bwrap` (bubblewrap) binary.
  On Ubuntu 24.04+ this fails with `bwrap: setting up uid map: Permission
  denied` because of the AppArmor `apparmor_restrict_unprivileged_userns=1`
  default - unrelated to hooks, breaks all sandboxed writes. Fixed on this
  VPS with a scoped AppArmor profile at `/etc/apparmor.d/codex-bwrap`
  (glob-matched to the nvm-installed bwrap path, so it survives Node/Codex
  version bumps) rather than disabling the restriction system-wide.

## Phase 1 guard smoke test (LexNotify-Web pilot, 2026-07-27)

Ran live against the real repo with the guard wired via `.claude/settings.json`:

- Asked Claude Code to recreate the exact historical incident (`app/api/chat-processo/route.ts`,
  a "chat verticalizado por processo" route). The agent refused on its own first, citing
  `docs/architecture/DUPLICATION_INCIDENTS.json` and the existing canonical route - the
  instruction-file layer alone already caught it. When explicitly told to attempt the write
  anyway (to test the technical layer, not just agent judgment), the `Write` tool call was
  denied by the hook with the exact reason and canonical targets; no file was created; the
  agent did not attempt a workaround.
- A `docs/SCRATCH_NOTE.md` write (unrelated to any protected domain) went through normally,
  confirming the guard is scoped rather than blocking everything.
- **RESOLVED 2026-07-28**: the `ls`-family false positive from Phase 1 was root-caused and
  fixed. The redirection pattern `>>?(?!\s*/dev/null)` matched `2>&1` (fd-to-fd duplication,
  writes nothing to the filesystem) because it only excluded `/dev/null`, not `&N`/`&-`
  targets. Any shell command using `2>&1` (extremely common - stderr-to-stdout capture) was
  denied. Fixed by adding a second negative lookahead: `>>?(?!\s*/dev/null)(?!\s*&[-\d])`.
  Verified against a 20-case corpus (false positives now allowed: `2>&1`, `1>&2`, `>&-`, `>
  /dev/null 2>&1`; real mutations still denied: `> file`, `>> file`, `tee`, `sed -i`, `cp`,
  `mv`, `git apply`, PowerShell `Set-Content`/`Add-Content`/`Out-File`) - all pass. Also
  re-verified live end-to-end via `aak guard pretool --client claude`: `ls -la 2>&1` now
  allows (exit 0), a real dangerous write to a protected path still denies (exit 2).
- `docs/architecture/` had to be exempted from `.gitignore`'s blanket `/docs/*` rule (the repo
  treats most of `docs/` as local-only) - fixed by adding `!/docs/architecture/` +
  `!/docs/architecture/**`, following the existing per-folder exception pattern already used
  for `docs/user/`.

## Phase 2 hardening: Codex smoke test in the real repo, and a self-grant gap it exposed

Ran the same "recreate the chat-processo route" test against Codex directly in
`~/projects/LexNotify-Web` (not an isolated test dir): trusted the hook via the TUI once,
then asked Codex to create the route with `apply_patch`. It read `AGENTS.md` and the
architecture map on its own, decided to build the route as a thin wrapper around the
canonical `getOrCreateCaseChat` (good judgment), attempted the write anyway - and the
`PreToolUse` hook denied it with the correct reason. No workaround attempted at first.

It then **did** try something worth flagging: it ran
`aak task start --executor codex --allow-new app/api/chat-processo/route.ts --ttl-hours 1`
directly as a shell command, to manufacture its own covering task decision. This only failed
because Codex's own sandbox denies writes outside the project workdir (the protected state
root `/srv/agent-architecture/state/` is outside it) - not because this kit stopped it. The
shell guard's dangerous-pattern list did not cover this command (no redirect/tee/sed/cp/mv/git
apply), so it would have gone through under `-s danger-full-access` or under a client without
Codex's workdir-scoped sandbox (e.g. nothing stopped this same shell call from a Claude Code
session before this fix).

**Fixed**: added `SELF_GRANT_SHELL_RE` to `guard.py` - any shell command matching
`aak\s+(task\s+start|override\s+create)` is denied outright, regardless of client sandbox
behavior. This is deterministic defense in depth, not a full solution: there is still no
OS-level guarantee that a differently-worded or obfuscated self-grant attempt, or a write via
an MCP filesystem tool the guard doesn't intercept, couldn't reach the same state files. Real
separation (task/override commands only reachable by a human-operated path, e.g. a different
OS user or a network-gated service) is the actual fix and is a gap to close before this pilot
generalizes past a single operator.

## Pre-commit layer and a known trade-off

Wired `aak guard precommit` via `.githooks/pre-commit` (`git config core.hooksPath .githooks`,
committed so it's shared across clones - plain `.git/hooks/` isn't versioned). It checks every
staged file against the same protected-domain/decision/override logic as pretool/posttool.

Trade-off made deliberately: precommit does **not** apply the self-edit-forbidden check
(`.claude/settings.json`, `.agent-architecture/`, etc.) that pretool/posttool enforce, because
that would have blocked committing the kit's own legitimate one-time setup. This means a
maliciously-edited `.claude/settings.json` that somehow survived pretool+posttool (both already
deny edits to it) would not be caught again at commit time by this local layer. That's an
accepted gap for Phase 1: the real backstop for tampered guard config is deterministic CI running
server-side, outside agent control (see the CI section below) - the master plan is explicit that
"no single layer is sufficient" and treats local Git hooks as a lightweight/bypassable layer, not
the final boundary.

## Gemini CLI

- Authentication was not completed for this pilot (decision made 2026-07-27:
  "Sign in with Google" OAuth succeeded but the CLI still demanded a paired
  API key afterward; skipped and treated as a separate pending item).
  `write_file`/`replace`/`run_shell_command` hook payload shapes are
  therefore **unverified** - the `gemini` adapter in this kit is a stub, not
  a tested implementation. Do not rely on it for a Gemini-as-executor
  scenario without re-verifying.

## KVM4 infra reaudit (2026-07-28)

The master plan's swap/build-lock sizing (8-16GB swap, N concurrent heavy
tasks) was calculated for a KVM8 the plan originally assumed - the VPS
actually contracted and provisioned is a KVM4 (half the specs, downgraded
earlier for cost reasons). Real specs confirmed live via `nproc`/`free -h`/`df -h`:

- 4 vCPU, 15GB RAM, **0 swap** (until this finding), 193GB disk (183GB free)

Zero swap on a 4-vCPU box running a self-hosted CI runner plus interactive
Claude Code/Codex sessions is a real risk, not theoretical - this same
session hit real single-runner contention (multiple PRs' CI jobs serialized,
one job queued ~20 minutes behind another). Actions taken, both low-risk
(reversible, no VPS resize, well within the 183GB free disk already paid
for):

- 4GB swapfile created (`fallocate`+`mkswap`+`swapon`), persisted via
  `/etc/fstab` (`/swapfile none swap sw 0 0`).
- `vm.swappiness` set to 10 (from the Linux default of 60) via
  `/etc/sysctl.d/99-swappiness.conf` - prefer RAM until genuinely needed,
  swap is a safety net against OOM-kill during a heavy `npm ci`/build, not a
  primary memory extension for routine workloads.
- `bin/with-build-lock.sh` (flock semaphore, see README) added as a
  complementary mitigation for the CI-queue-contention half of the problem;
  it doesn't fix the queue itself, just keeps *manual* heavy commands from
  compounding it.

Not done, and deliberately out of scope here: resizing the VPS itself (would
cost money, needs an explicit ROI conversation) and fixing the CI queue depth
itself (more runners, or job-level concurrency limits in each workflow - a
bigger change than this reaudit's scope).
