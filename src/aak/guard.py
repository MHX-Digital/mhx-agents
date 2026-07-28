"""Core pre-tool and post-tool guard logic, shared by both client adapters.

Phase 1 scope: keyword-based protected-domain matching against the active
task decision, plus a minimal shell deny-pattern list (section 5.5 of the
master plan). This is deterministic, not semantic - it is the floor the
plan asks to verify before building anything more elaborate on top.
"""
import fnmatch
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import adapters
from . import decision as decision_mod
from . import override as override_mod
from .manifest import ManifestError, load_manifest
from .paths import KIT_ROOT, find_repo_root, state_root

DANGEROUS_SHELL_PATTERNS = [
    # Redirection, except discarding to /dev/null or fd-to-fd duplication
    # (2>&1, 1>&2, >&-) - those never touch the filesystem. Found live
    # 2026-07-28: a read-only `ls ... 2>&1` was denied because `2>&1` matched
    # the bare ">" pattern; the false positive was in the shell corpus, not
    # the guard's intent (section 5.5 only wants to catch writes to files).
    r">>?(?!\s*/dev/null)(?!\s*&[-\d])",
    r"\btee\b",
    r"\bsed\s+-i\b",
    r"\bcp\b",
    r"\bmv\b",
    r"\bgit\s+apply\b",
    r"Set-Content\b",
    r"Add-Content\b",
    r"Out-File\b",
]
DANGEROUS_SHELL_RE = re.compile("|".join(DANGEROUS_SHELL_PATTERNS))

# Section 5.7: an agent must not be able to self-grant the authority the
# guard checks against, by shelling out to the kit's own write commands.
# Found live during Phase 1 testing: Codex, blocked from creating a
# duplicate route, tried running `aak task start` itself to manufacture a
# covering decision - it only failed because its sandbox denied writes
# outside the project workdir (/srv/agent-architecture/state is outside
# it). That is a sandbox accident, not a guarantee; this pattern closes the
# gap directly regardless of sandbox behavior.
SELF_GRANT_SHELL_RE = re.compile(r"\baak\s+(task\s+start|override\s+create)\b")

# Section 5.7: agents may not create/edit overrides, hooks, protected state,
# or guard configuration, regardless of domain or active decision.
SELF_EDIT_FORBIDDEN_PATHS = [
    ".architecture-override",
    ".agent-architecture/*",
    ".agent-architecture/**",
    ".claude/settings.json",
    ".codex/config.toml",
    ".codex/hooks.json",
]


@dataclass
class GuardResult:
    allowed: bool
    reason: str

    @property
    def exit_code(self) -> int:
        return 0 if self.allowed else 2


def _relative_path(target: str, repo_root: Path) -> str:
    p = Path(target)
    if p.is_absolute():
        try:
            return str(p.relative_to(repo_root)).replace("\\", "/")
        except ValueError:
            return str(p).replace("\\", "/")
    return str(p).replace("\\", "/")


def _is_forbidden_self_edit(rel_path: str, target_path: str) -> bool:
    if any(fnmatch.fnmatch(rel_path, pattern) for pattern in SELF_EDIT_FORBIDDEN_PATHS):
        return True
    # Also forbid writes that resolve (absolute) inside the kit install or
    # the protected state root, however the path was expressed.
    try:
        resolved = Path(target_path).resolve()
    except (OSError, ValueError):
        return False
    for guarded_root in (KIT_ROOT, state_root()):
        try:
            resolved.relative_to(guarded_root)
            return True
        except ValueError:
            continue
    return False


def _match_protected_domain(rel_path: str, protected_domains: list[str]) -> str | None:
    lowered = rel_path.lower()
    for domain in protected_domains:
        if domain.lower() in lowered:
            return domain
    return None


def _matches_generated(rel_path: str, generated_paths: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel_path, pattern) for pattern in generated_paths)


def _load_incidents(manifest) -> list[dict]:
    path = manifest.incidents_path
    if not path.is_file():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _incidents_for_domain(incidents: list[dict], domain: str, rel_path: str) -> list[dict]:
    domain_l = domain.lower()
    path_tokens = set(re.split(r"[/_.\-]+", rel_path.lower()))
    matches = []
    for inc in incidents:
        target = inc.get("canonicalTarget") or {}
        haystack = " ".join([
            target.get("path", ""),
            " ".join(inc.get("businessTerms", [])),
            " ".join(inc.get("acceptedAliases", [])),
        ]).lower()
        if domain_l in haystack or (path_tokens & set(re.split(r"[/_.\-\s]+", haystack))):
            matches.append(inc)
    return matches


def _format_incident_hint(incidents: list[dict]) -> str:
    if not incidents:
        return "no recorded canonical target; verify manually before creating a new path."
    parts = []
    for inc in incidents:
        target = inc.get("canonicalTarget") or {}
        parts.append(f"{target.get('path', '?')} ({target.get('symbol', '?')})")
    return "known canonical target(s): " + "; ".join(parts)


def _allowed_by_decision(rel_path: str, decision: dict) -> bool:
    existing = decision.get("allowedExistingPaths", [])
    new = decision.get("allowedNewPaths", [])
    if rel_path in existing or rel_path in new:
        return True
    # allow writes inside an approved directory prefix (e.g. "src/domain/cases/**")
    for allowed in existing + new:
        allowed_norm = allowed.rstrip("/*")
        if rel_path == allowed_norm or rel_path.startswith(allowed_norm + "/"):
            return True
    return False


def _check_write_path(rel_path: str, manifest, repo_root: Path, check_self_edit: bool = True) -> GuardResult:
    """Shared allow/deny decision for a single path.

    `check_self_edit` is True for pretool/posttool (an agent tool call is
    live) and False for precommit: committing kit config is exactly how the
    operator's legitimate one-time setup gets versioned, so the commit-time
    layer only checks protected-domain/decision/override, not self-edit. The
    self-edit ban's job is to stop an agent from doing this *during its own
    session*, which pretool/posttool cover; precommit would otherwise block
    the setup it's supposed to allow."""
    if check_self_edit and _is_forbidden_self_edit(rel_path, str(repo_root / rel_path)):
        return GuardResult(
            False,
            f"'{rel_path}' is guard/override/protected-state configuration; agents may not "
            f"create or edit it (section 5.7)",
        )

    if _matches_generated(rel_path, manifest.generated_paths):
        return GuardResult(True, f"'{rel_path}' matches a declared generated path")

    domain = _match_protected_domain(rel_path, manifest.protected_domains)
    if domain is None:
        return GuardResult(True, f"'{rel_path}' is outside all protected domains")

    overrides = override_mod.load_active_overrides(manifest.repo_id)

    active_decision = decision_mod.load_decision(manifest.repo_id)
    if active_decision is not None:
        valid, reason = decision_mod.validate_decision(active_decision, repo_root)
        if valid and _allowed_by_decision(rel_path, active_decision):
            return GuardResult(True, f"'{rel_path}' is covered by the active task decision")
        if not valid:
            active_decision = None  # fall through to override/deny path

    override_hit = override_mod.covers_path(rel_path, overrides)
    if override_hit is not None:
        return GuardResult(
            True,
            f"'{rel_path}' is covered by override for issue {override_hit['issue']} "
            f"(scope '{override_hit['scope']}')",
        )

    incidents = _incidents_for_domain(_load_incidents(manifest), domain, rel_path)
    if active_decision is None:
        return GuardResult(
            False,
            f"'{rel_path}' is in protected domain '{domain}' and no active task decision or "
            f"override exists; {_format_incident_hint(incidents)}",
        )
    allowed_list = active_decision.get("allowedExistingPaths", []) + active_decision.get("allowedNewPaths", [])
    return GuardResult(
        False,
        f"'{rel_path}' is in protected domain '{domain}' but not covered by the active task "
        f"decision (allowed: {allowed_list}) or any override; {_format_incident_hint(incidents)}",
    )


def evaluate(client: str, payload: dict, cwd: Path) -> GuardResult:
    """PreToolUse: evaluate a single proposed write/shell call before it runs."""
    repo_root = find_repo_root(cwd)
    if repo_root is None:
        return GuardResult(True, "not inside an agent-architecture-managed repository")

    try:
        manifest = load_manifest(repo_root)
    except ManifestError as e:
        return GuardResult(False, f"fail-closed: {e}")

    call = adapters.normalize(client, payload)

    if call.kind == "other":
        return GuardResult(True, f"tool '{call.raw_tool_name}' is not a guarded write/shell tool")

    if call.kind == "shell":
        command = call.command or ""
        if SELF_GRANT_SHELL_RE.search(command):
            return GuardResult(
                False,
                "agents may not run 'aak task start' or 'aak override create' themselves to "
                "self-grant the authority this guard checks against (section 5.7); these must be "
                "run by the owner outside the agent session",
            )
        known_validations = list(manifest.validation.values())
        if any(command.strip().startswith(v) for v in known_validations):
            return GuardResult(True, "matches an allow-listed validation command")
        if DANGEROUS_SHELL_RE.search(command):
            return GuardResult(
                False,
                "shell command contains a file-mutating pattern (redirection/tee/sed -i/cp/mv/"
                "git apply/Set-Content/Add-Content/Out-File); not covered by an exact task-decision "
                "exception (section 5.5)",
            )
        return GuardResult(True, "shell command has no recognized file-mutating pattern")

    # call.kind == "write"
    if not call.target_path:
        return GuardResult(False, "fail-closed: could not determine target path from tool payload")

    rel_path = _relative_path(call.target_path, repo_root)
    return _check_write_path(rel_path, manifest, repo_root)


def _changed_paths(repo_root: Path, since_sha: str | None) -> list[str]:
    """Files touched in the working tree, relative to repo_root.

    With since_sha: everything changed since the task decision's baseSha
    (catches shell-mediated writes across the whole task, not just the last
    tool call). Without it: just the current uncommitted working-tree diff
    (defense in depth for when no decision is active at all).
    """
    if since_sha:
        cmd = ["git", "-C", str(repo_root), "diff", "--name-only", since_sha]
    else:
        cmd = ["git", "-C", str(repo_root), "status", "--porcelain"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        return []
    if since_sha:
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    # `git status --porcelain` lines look like "XY path" or "XY orig -> new"
    paths = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        rest = line[3:].strip()
        path = rest.split(" -> ")[-1]
        paths.append(path)
    return paths


def evaluate_posttool(client: str, payload: dict, cwd: Path) -> GuardResult:
    """PostToolUse: scope-drift check across all files touched so far, not
    just the one named in this event's payload (section 5.1/5.3). Cannot
    undo a write that already happened - a deny here means "stop the
    session and review", not "this was blocked"."""
    repo_root = find_repo_root(cwd)
    if repo_root is None:
        return GuardResult(True, "not inside an agent-architecture-managed repository")

    try:
        manifest = load_manifest(repo_root)
    except ManifestError as e:
        return GuardResult(False, f"fail-closed: {e}")

    call = adapters.normalize(client, payload)
    if call.kind == "other":
        return GuardResult(True, f"tool '{call.raw_tool_name}' has no filesystem side effects to check")

    active_decision = decision_mod.load_decision(manifest.repo_id)
    since_sha = active_decision.get("baseSha") if active_decision else None
    changed = _changed_paths(repo_root, since_sha)

    drift = []
    for rel_path in changed:
        result = _check_write_path(rel_path, manifest, repo_root)
        if not result.allowed:
            drift.append((rel_path, result.reason))

    if drift:
        details = "; ".join(f"{p}: {r}" for p, r in drift)
        return GuardResult(
            False,
            f"scope drift detected across {len(drift)} file(s) touched this task - stop and review "
            f"before continuing: {details}",
        )
    return GuardResult(True, f"no scope drift across {len(changed)} touched file(s)")


def evaluate_precommit(cwd: Path) -> GuardResult:
    """Git pre-commit layer (table 5.1): catches manual edits and tool
    bypasses that never went through a PreToolUse/PostToolUse hook at all -
    a different editor, a filesystem MCP tool the guard doesn't intercept,
    or a client with hooks disabled. Checks every staged file, not just the
    working tree, since that's what's about to become part of history."""
    repo_root = find_repo_root(cwd)
    if repo_root is None:
        return GuardResult(True, "not inside an agent-architecture-managed repository")

    try:
        manifest = load_manifest(repo_root)
    except ManifestError as e:
        return GuardResult(False, f"fail-closed: {e}")

    result = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--cached", "--name-only"],
        capture_output=True, text=True, timeout=15,
    )
    staged = [line.strip() for line in result.stdout.splitlines() if line.strip()]

    violations = []
    for rel_path in staged:
        check = _check_write_path(rel_path, manifest, repo_root, check_self_edit=False)
        if not check.allowed:
            violations.append((rel_path, check.reason))

    if violations:
        details = "; ".join(f"{p}: {r}" for p, r in violations)
        return GuardResult(
            False,
            f"commit blocked - {len(violations)} staged file(s) violate the architecture guard: "
            f"{details}",
        )
    return GuardResult(True, f"{len(staged)} staged file(s) clear")
