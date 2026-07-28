"""Protected task decision: create, load, and staleness validation.

Phase 1 simplification: one active decision per repo (no worktree/parallel-task
support yet). Storage lives outside the writable repository, per the master
plan section 4.2.
"""
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .paths import decisions_dir
from . import __version__ as KIT_VERSION


class DecisionError(Exception):
    pass


def _sanitize_repo_id(repo_id: str) -> str:
    return repo_id.replace("/", "__")


def _decision_path(repo_id: str) -> Path:
    return decisions_dir() / f"{_sanitize_repo_id(repo_id)}.json"


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise DecisionError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def current_branch(repo_root: Path) -> str:
    return _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")


def current_sha(repo_root: Path) -> str:
    return _git(repo_root, "rev-parse", "HEAD")


def create_decision(
    repo_root: Path,
    manifest,
    executor: str,
    allowed_existing_paths: list[str],
    allowed_new_paths: list[str],
    issue: int | None = None,
    ttl_hours: int = 24,
    verdict: str = "MANUAL_APPROVED",
) -> dict:
    now = datetime.now(timezone.utc)
    decision = {
        "schemaVersion": "1.0",
        "kitVersion": KIT_VERSION,
        "repoId": manifest.repo_id,
        "tier": manifest.tier,
        "issue": issue,
        "branch": current_branch(repo_root),
        "executor": executor,
        "baseSha": current_sha(repo_root),
        "mapHash": None,
        "createdAt": now.isoformat(),
        "expiresAt": (now + timedelta(hours=ttl_hours)).isoformat(),
        "verdict": verdict,
        "allowedExistingPaths": allowed_existing_paths,
        "allowedNewPaths": allowed_new_paths,
        "protectedDomains": manifest.protected_domains,
        "requiredValidations": list(manifest.validation.keys()),
        "overrideId": None,
    }
    path = _decision_path(manifest.repo_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(decision, f, indent=2)
    return decision


def load_decision(repo_id: str) -> dict | None:
    path = _decision_path(repo_id)
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_decision(decision: dict, repo_root: Path) -> tuple[bool, str]:
    """Returns (is_valid, reason). Invalid means deny, not warn (section 4.3)."""
    try:
        expires_at = datetime.fromisoformat(decision["expiresAt"])
        if datetime.now(timezone.utc) > expires_at:
            return False, "task decision expired"

        branch_now = current_branch(repo_root)
        if branch_now != decision["branch"]:
            return False, f"branch changed ({decision['branch']} -> {branch_now})"

        base_sha = decision["baseSha"]
        result = subprocess.run(
            ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", base_sha, "HEAD"],
            capture_output=True, timeout=10,
        )
        if result.returncode != 0:
            return False, "HEAD is no longer descended from baseSha"

    except DecisionError as e:
        return False, str(e)
    except (KeyError, ValueError) as e:
        return False, f"malformed decision: {e}"

    return True, "valid"
