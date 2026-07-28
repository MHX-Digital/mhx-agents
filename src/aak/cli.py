import argparse
import json
import sys
from pathlib import Path

from . import __version__
from . import decision as decision_mod
from . import doctor as doctor_mod
from . import guard as guard_mod
from . import hooks as hooks_mod
from . import orchestrate as orchestrate_mod
from . import override as override_mod
from .manifest import ManifestError, load_manifest
from .paths import find_repo_root


def cmd_doctor(args) -> int:
    print(doctor_mod.run())
    return 0


def cmd_guard_pretool(args) -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"fail-closed: invalid JSON on stdin: {e}", file=sys.stderr)
        return 2

    cwd = Path(payload.get("cwd", ".")).resolve() if payload.get("cwd") else Path.cwd()

    try:
        result = guard_mod.evaluate(args.client, payload, cwd)
    except Exception as e:  # fail-closed on any internal error, per section 5.6
        print(f"fail-closed: internal guard error: {e}", file=sys.stderr)
        return 2

    if not result.allowed:
        print(result.reason, file=sys.stderr)
        return 2
    return 0


def cmd_guard_posttool(args) -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"fail-closed: invalid JSON on stdin: {e}", file=sys.stderr)
        return 2

    cwd = Path(payload.get("cwd", ".")).resolve() if payload.get("cwd") else Path.cwd()

    try:
        result = guard_mod.evaluate_posttool(args.client, payload, cwd)
    except Exception as e:
        print(f"fail-closed: internal guard error: {e}", file=sys.stderr)
        return 2

    if not result.allowed:
        print(result.reason, file=sys.stderr)
        return 2
    return 0


def cmd_guard_precommit(args) -> int:
    try:
        result = guard_mod.evaluate_precommit(Path.cwd())
    except Exception as e:
        print(f"fail-closed: internal guard error: {e}", file=sys.stderr)
        return 2

    if not result.allowed:
        print(result.reason, file=sys.stderr)
        return 1
    return 0


def cmd_override_create(args) -> int:
    repo_root = find_repo_root(Path.cwd())
    if repo_root is None:
        print("error: not inside an agent-architecture-managed repository", file=sys.stderr)
        return 1
    try:
        manifest = load_manifest(repo_root)
    except ManifestError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    override = override_mod.create_override(
        repo_id=manifest.repo_id,
        issue=args.issue,
        scope=args.scope,
        reason=args.reason,
        expires_at=args.expires,
        repo_root=repo_root,
    )
    print(json.dumps(override, indent=2))
    print(f"\nReceipt written to {repo_root / '.architecture-override'} (commit it for audit trail).")
    return 0


def cmd_task_start(args) -> int:
    repo_root = find_repo_root(Path.cwd())
    if repo_root is None:
        print("error: not inside an agent-architecture-managed repository", file=sys.stderr)
        return 1
    try:
        manifest = load_manifest(repo_root)
    except ManifestError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    decision = decision_mod.create_decision(
        repo_root=repo_root,
        manifest=manifest,
        executor=args.executor,
        allowed_existing_paths=args.allow_existing or [],
        allowed_new_paths=args.allow_new or [],
        issue=args.issue,
        ttl_hours=args.ttl_hours,
    )
    print(json.dumps(decision, indent=2))
    return 0


def cmd_task_status(args) -> int:
    repo_root = find_repo_root(Path.cwd())
    if repo_root is None:
        print("error: not inside an agent-architecture-managed repository", file=sys.stderr)
        return 1
    try:
        manifest = load_manifest(repo_root)
    except ManifestError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    decision = decision_mod.load_decision(manifest.repo_id)
    if decision is None:
        print(f"no active task decision for repo '{manifest.repo_id}'")
        return 0

    valid, reason = decision_mod.validate_decision(decision, repo_root)
    print(json.dumps(decision, indent=2))
    print(f"\nstatus: {'VALID' if valid else 'STALE/INVALID'} ({reason})")
    return 0


def cmd_orchestrate(args) -> int:
    repo_root = Path(args.repo).resolve() if args.repo else Path.cwd()
    try:
        result = orchestrate_mod.run(
            repo_root=repo_root,
            request=args.request,
            executor=args.executor,
            ttl_hours=args.ttl_hours,
            issue=args.issue,
        )
    except orchestrate_mod.OrchestrateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    plan = result["plan"]
    print(f"codex verdict: {plan['verdict']}")
    print(f"summary: {plan['summary']}")
    print(f"reasoning: {plan['reasoning']}")

    if result["stopped"]:
        print(f"\nSTOPPED — verdict '{plan['verdict']}' does not proceed (fail-closed). "
              f"No task decision created, Claude Code not invoked.", file=sys.stderr)
        return 2

    decision = result["decision"]
    print(f"\ntask decision created: executor={decision['executor']} "
          f"expiresAt={decision['expiresAt']}")
    print(f"allowedExistingPaths: {decision['allowedExistingPaths']}")
    print(f"allowedNewPaths: {decision['allowedNewPaths']}")
    print(f"\n--- claude code execution output ---\n{result['execution_output']}")
    return 0


def _hook_cwd(payload: dict) -> Path:
    return Path(payload.get("cwd", ".")).resolve() if payload.get("cwd") else Path.cwd()


def cmd_hook_session_start(args) -> int:
    # Advisory only: any error here must never block a session from starting.
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    try:
        context = hooks_mod.session_start_context(_hook_cwd(payload))
    except Exception:
        return 0
    if context:
        print(json.dumps({"additionalContext": context}))
    return 0


def cmd_hook_prompt_submit(args) -> int:
    # Advisory only: any error here must never block the user's prompt.
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    try:
        context = hooks_mod.prompt_submit_context(_hook_cwd(payload), payload.get("prompt", ""))
    except Exception:
        return 0
    if context:
        print(json.dumps({"additionalContext": context}))
    return 0


def cmd_hook_stop(args) -> int:
    # Advisory only: any error here must never block a session from ending.
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    try:
        message = hooks_mod.maybe_regen_map(_hook_cwd(payload))
    except Exception:
        return 0
    if message:
        print(message, file=sys.stderr)
    return 0


def cmd_mcp_serve(args) -> int:
    # imported lazily: the mcp SDK is a heavy dependency (starlette/uvicorn/etc)
    # that every other subcommand (esp. `guard pretool`, run on every tool call
    # by the PreToolUse hook) would otherwise pay import cost for on every run.
    from . import mcp_server as mcp_server_mod

    repo_root = Path(args.repo_root).resolve()
    try:
        mcp_server_mod.serve(repo_root)
    except ManifestError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aak", description="Agent Architecture Kit")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="report client install/auth/capability status").set_defaults(func=cmd_doctor)

    guard = sub.add_parser("guard", help="pre/post-tool guard commands")
    guard_sub = guard.add_subparsers(dest="guard_command", required=True)
    pretool = guard_sub.add_parser("pretool", help="evaluate a PreToolUse hook payload from stdin")
    pretool.add_argument("--client", required=True, choices=["claude", "codex"])
    pretool.set_defaults(func=cmd_guard_pretool)
    posttool = guard_sub.add_parser("posttool", help="evaluate a PostToolUse hook payload from stdin (scope-drift check)")
    posttool.add_argument("--client", required=True, choices=["claude", "codex"])
    posttool.set_defaults(func=cmd_guard_posttool)
    precommit = guard_sub.add_parser("precommit", help="check staged files before a git commit")
    precommit.set_defaults(func=cmd_guard_precommit)

    override = sub.add_parser("override", help="protected override commands (run outside any agent session)")
    override_sub = override.add_subparsers(dest="override_command", required=True)
    override_create = override_sub.add_parser("create", help="record an owner-approved scoped exception")
    override_create.add_argument("--issue", type=int, required=True)
    override_create.add_argument("--scope", required=True, help="glob pattern, e.g. 'src/chat/**'")
    override_create.add_argument("--reason", required=True)
    override_create.add_argument("--expires", required=True, help="ISO-8601 datetime")
    override_create.set_defaults(func=cmd_override_create)

    task = sub.add_parser("task", help="protected task decision commands")
    task_sub = task.add_subparsers(dest="task_command", required=True)

    task_start = task_sub.add_parser("start", help="create a protected task decision for the current repo")
    task_start.add_argument("--executor", required=True, choices=["claude", "codex"])
    task_start.add_argument("--issue", type=int, default=None)
    task_start.add_argument("--allow-existing", nargs="*", default=[])
    task_start.add_argument("--allow-new", nargs="*", default=[])
    task_start.add_argument("--ttl-hours", type=int, default=24)
    task_start.set_defaults(func=cmd_task_start)

    task_status = task_sub.add_parser("status", help="show the active task decision for the current repo")
    task_status.set_defaults(func=cmd_task_status)

    orchestrate = sub.add_parser(
        "orchestrate",
        help="Codex plans (read-only) -> protected task decision -> Claude Code executes (headless)",
    )
    orchestrate.add_argument("--repo", default=None, help="repo path (default: cwd)")
    orchestrate.add_argument("--request", required=True, help="what to build/change, in plain language")
    orchestrate.add_argument("--executor", default="claude", choices=["claude"])
    orchestrate.add_argument("--ttl-hours", type=int, default=24)
    orchestrate.add_argument("--issue", type=int, default=None)
    orchestrate.set_defaults(func=cmd_orchestrate)

    mcp_parser = sub.add_parser("mcp", help="MCP server commands")
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_command", required=True)
    mcp_serve = mcp_sub.add_parser(
        "serve",
        help="serve the architecture-map MCP server (stdio) for a repo",
    )
    mcp_serve.add_argument("--repo-root", required=True, help="path to the repo this MCP instance serves")
    mcp_serve.set_defaults(func=cmd_mcp_serve)

    hook = sub.add_parser("hook", help="advisory (non-blocking) hook commands - never deny, only inform")
    hook_sub = hook.add_subparsers(dest="hook_command", required=True)
    hook_sub.add_parser(
        "session-start",
        help="SessionStart advisory context: repo tier + active task decision status",
    ).set_defaults(func=cmd_hook_session_start)
    hook_sub.add_parser(
        "prompt-submit",
        help="UserPromptSubmit advisory context: protected-domain/known-incident keyword match",
    ).set_defaults(func=cmd_hook_prompt_submit)
    hook_sub.add_parser(
        "stop",
        help="Stop hook: debounced incremental architecture-map regen if source changed",
    ).set_defaults(func=cmd_hook_stop)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
