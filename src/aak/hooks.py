"""Advisory (non-blocking) hook payloads for UserPromptSubmit and SessionStart.

Unlike guard.py, nothing here can deny anything - these hooks only ever inject
additionalContext, or print nothing at all. Silence when there's no repo
manifest, or when nothing in the prompt matches a known trigger, is
intentional: noise on every unrelated prompt would just get tuned out and
ignored over time, defeating the point.
"""
import json
from pathlib import Path

from . import decision as decision_mod
from .manifest import ManifestError, load_manifest
from .paths import find_repo_root


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
