"""Advisory (non-blocking) hook payloads for UserPromptSubmit and SessionStart.

Unlike guard.py, nothing here can deny anything - these hooks only ever inject
additionalContext, or print nothing at all. Silence when there's no repo
manifest, or when nothing in the prompt matches a known trigger, is
intentional: noise on every unrelated prompt would just get tuned out and
ignored over time, defeating the point.
"""
import json
import subprocess
import time
from pathlib import Path

from . import decision as decision_mod
from .manifest import ManifestError, load_manifest
from .paths import find_repo_root, locks_dir

MAP_REGEN_DEBOUNCE_SECONDS = 30
SOURCE_EXTENSIONS = (".ts", ".tsx")


def _load_incidents(manifest) -> list[dict]:
    path = manifest.incidents_path
    if not path.is_file():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def session_start_context(cwd: Path) -> str | None:
    """SessionStart: surface repo tier + active task decision status, if any."""
    repo_root = find_repo_root(cwd)
    if repo_root is None:
        return None
    try:
        manifest = load_manifest(repo_root)
    except ManifestError:
        return None

    lines = [f"[agent-architecture-kit] repo '{manifest.repo_id}', tier {manifest.tier}."]
    decision = decision_mod.load_decision(manifest.repo_id)
    if decision is None:
        lines.append(
            "No active task decision - writes to protected domains will be denied until "
            "one is created (`aak task start`)."
        )
    else:
        valid, reason = decision_mod.validate_decision(decision, repo_root)
        status = "valid" if valid else f"INVALID ({reason})"
        issue = decision.get("issue")
        lines.append(
            f"Active task decision for issue #{issue if issue else '?'} on branch "
            f"'{decision.get('branch')}': {status}, expires {decision.get('expiresAt')}."
        )
    return "\n".join(lines)


def prompt_submit_context(cwd: Path, prompt: str) -> str | None:
    """UserPromptSubmit: flag protected-domain/known-incident keyword matches."""
    repo_root = find_repo_root(cwd)
    if repo_root is None:
        return None
    try:
        manifest = load_manifest(repo_root)
    except ManifestError:
        return None

    prompt_l = prompt.lower()
    hits = []

    for domain in manifest.protected_domains:
        if domain and domain.lower() in prompt_l:
            hits.append(f"protected domain '{domain}'")

    for incident in _load_incidents(manifest):
        terms = [t for t in incident.get("businessTerms", []) + incident.get("acceptedAliases", []) if t]
        if any(term.lower() in prompt_l for term in terms):
            target = incident.get("canonicalTarget") or {}
            hits.append(
                f"possible match with a known duplication incident ({incident.get('date', '?')}): "
                f"canonical target is {target.get('path', '?')} ({target.get('symbol', '?')}) - "
                f"check it before creating something new"
            )

    if not hits:
        return None
    return "[agent-architecture-kit] " + " | ".join(hits)


def _map_regen_debounce_path(repo_id: str) -> Path:
    return locks_dir() / f"map-regen-debounce-{repo_id.replace('/', '__')}.json"


def _recently_regenerated(repo_id: str) -> bool:
    path = _map_regen_debounce_path(repo_id)
    if not path.is_file():
        return False
    try:
        last_run_at = json.loads(path.read_text())["lastRunAt"]
    except (json.JSONDecodeError, KeyError, OSError, ValueError):
        return False
    return (time.time() - last_run_at) < MAP_REGEN_DEBOUNCE_SECONDS


def _record_map_regen(repo_id: str) -> None:
    path = _map_regen_debounce_path(repo_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"lastRunAt": time.time()}))


def _has_uncommitted_source_changes(repo_root: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        return False
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        changed_path = line[3:].strip().split(" -> ")[-1]
        if changed_path.endswith(SOURCE_EXTENSIONS):
            return True
    return False


def maybe_regen_map(cwd: Path) -> str | None:
    """Stop hook: regenerate the architecture map if source changed since the
    last regen, at most once per MAP_REGEN_DEBOUNCE_SECONDS. Reuses the repo's
    own scripts/agent-architecture/scan_architecture.py (already tested, wired
    into CI's architecture-drift check) rather than reimplementing scanning
    logic here - this function only decides whether and how often to run it.
    """
    repo_root = find_repo_root(cwd)
    if repo_root is None:
        return None
    try:
        manifest = load_manifest(repo_root)
    except ManifestError:
        return None

    scanner = repo_root / "scripts" / "agent-architecture" / "scan_architecture.py"
    if not scanner.is_file():
        return None

    if not _has_uncommitted_source_changes(repo_root):
        return None
    if _recently_regenerated(manifest.repo_id):
        return None

    result = subprocess.run(
        ["python3", str(scanner), str(repo_root)],
        capture_output=True, text=True, timeout=120,
    )
    _record_map_regen(manifest.repo_id)
    if result.returncode != 0:
        return f"[agent-architecture-kit] map regen failed: {result.stderr.strip()[:500]}"
    return "[agent-architecture-kit] architecture map regenerated (uncommitted source changes detected)."
