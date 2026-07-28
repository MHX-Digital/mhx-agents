"""Protected overrides (master plan section 5.7).

Phase 1 honesty note: this kit runs everything as the single `mhx` OS user
(no separate agent/owner accounts yet), so there is no OS-level guarantee
that `aak override create` was run "outside the agent session" as the plan
requires. What IS enforced technically: the guard (see guard.py's
_is_forbidden_self_edit) always denies agent write attempts to
.architecture-override, .agent-architecture/, .claude/settings.json, or
anything under the kit/state roots, regardless of domain or active decision.
Real separation (a human-only path to this command) is a gap to close before
this goes beyond a single-operator pilot.
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .paths import overrides_dir


def _sanitize_repo_id(repo_id: str) -> str:
    return repo_id.replace("/", "__")


def _overrides_path(repo_id: str) -> Path:
    return overrides_dir() / f"{_sanitize_repo_id(repo_id)}.json"


def _authorization_hash(repo_id: str, issue: int, scope: str, reason: str, expires_at: str) -> str:
    payload = f"{repo_id}|{issue}|{scope}|{reason}|{expires_at}".encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def create_override(
    repo_id: str,
    issue: int,
    scope: str,
    reason: str,
    expires_at: str,
    repo_root: Path | None = None,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    override = {
        "schemaVersion": "1.0",
        "repoId": repo_id,
        "issue": issue,
        "scope": scope,
        "reason": reason,
        "createdAt": now,
        "expiresAt": expires_at,
        "authorizationHash": _authorization_hash(repo_id, issue, scope, reason, expires_at),
    }

    path = _overrides_path(repo_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            existing = json.load(f)
    existing.append(override)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)

    if repo_root is not None:
        receipt_path = repo_root / ".architecture-override"
        receipt = {k: override[k] for k in ("issue", "scope", "reason", "expiresAt", "authorizationHash")}
        with open(receipt_path, "w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2)

    return override


def load_active_overrides(repo_id: str) -> list[dict]:
    path = _overrides_path(repo_id)
    if not path.is_file():
        return []
    with open(path, encoding="utf-8") as f:
        overrides = json.load(f)

    now = datetime.now(timezone.utc)
    active = []
    for o in overrides:
        try:
            expires = datetime.fromisoformat(o["expiresAt"])
            if now <= expires:
                active.append(o)
        except (KeyError, ValueError):
            continue
    return active


def covers_path(rel_path: str, overrides: list[dict]) -> dict | None:
    import fnmatch
    for o in overrides:
        if fnmatch.fnmatch(rel_path, o["scope"]):
            return o
    return None
