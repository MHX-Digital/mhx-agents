"""Recoverable lifecycle for architecture-map index publication.

The scanner remains the source of index content. This module owns isolation,
validation, immutable provenance, atomic promotion, rollback, and audit state.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .manifest import ProjectManifest

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ACTIVE_STATES = {"requested", "indexing", "validating", "ready", "publishing"}
TERMINAL_STATES = {"published", "failed", "rolled_back", "cancelled"}
TRANSITIONS = {
    "requested": {"indexing", "cancelled", "failed"},
    "indexing": {"validating", "cancelled", "failed"},
    "validating": {"ready", "cancelled", "failed"},
    "ready": {"publishing", "cancelled", "failed"},
    "publishing": {"published", "failed"},
}


class IndexLifecycleError(RuntimeError):
    """A safe, caller-facing lifecycle failure."""


@dataclass(frozen=True)
class Publication:
    run_id: str
    status: str
    manifest_path: Path
    artifact_path: Path
    previous_index: str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class IndexLifecycle:
    """Single-repository atomic index publisher.

    ``builder`` receives an isolated artifact path and the resolved commit. It
    must write a complete JSON index there; it never receives the active path.
    """

    def __init__(self, repo_root: Path, manifest: ProjectManifest, state_root: Path | None = None):
        self.repo_root = Path(repo_root).resolve()
        self.manifest = manifest
        self.active_path = manifest.map_path.resolve()
        self.state_root = (state_root or self.active_path.parent / ".index-state").resolve()
        if self.repo_root not in self.active_path.parents:
            raise IndexLifecycleError("active index is outside the repository root")
        if self.repo_root not in self.state_root.parents:
            raise IndexLifecycleError("index state root is outside the repository root")
        self.runs = self.state_root / "runs"
        self.snapshots = self.state_root / "snapshots"
        self.lock_path = self.state_root / "publish.lock"
        self.marker_path = self.active_path.with_suffix(self.active_path.suffix + ".indexing")
        self.audit_path = self.state_root / "audit.jsonl"

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.repo_root), *args], capture_output=True,
            text=True, timeout=15, check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise IndexLifecycleError("requested Git object could not be verified")
        return result.stdout.strip()

    def _resolve_target(self, branch: str, commit: str) -> str:
        if not isinstance(branch, str) or not branch or branch.startswith("-"):
            raise IndexLifecycleError("branch is invalid")
        if not isinstance(commit, str) or not SHA_RE.fullmatch(commit):
            raise IndexLifecycleError("commit must be a full 40-character SHA")
        resolved = self._git("rev-parse", "--verify", f"{commit}^{{commit}}")
        if resolved != commit:
            raise IndexLifecycleError("requested commit did not resolve exactly")
        branch_commit = None
        for ref in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"):
            try:
                branch_commit = self._git("rev-parse", "--verify", f"{ref}^{{commit}}")
                break
            except IndexLifecycleError:
                continue
        if branch_commit is None:
            raise IndexLifecycleError("requested branch is not available in the served repository")
        result = subprocess.run(
            ["git", "-C", str(self.repo_root), "merge-base", "--is-ancestor", commit, branch_commit],
            capture_output=True, timeout=15, check=False,
        )
        if result.returncode != 0:
            raise IndexLifecycleError("requested commit is outside the requested branch history")
        return resolved

    def _acquire(self, run_id: str) -> int:
        self.state_root.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise IndexLifecycleError("another index publisher holds the lock") from exc
        os.write(fd, run_id.encode("ascii"))
        os.fsync(fd)
        return fd

    def _release(self, fd: int) -> None:
        os.close(fd)
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass

    def _audit(self, event: dict) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        safe = {**event, "at": _now(), "repositoryId": self.manifest.repo_id}
        line = _canonical_json(safe) + b"\n"
        fd = os.open(self.audit_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)

    def _state(self, run_dir: Path, current: str | None, target: str, extra: dict | None = None) -> None:
        if current is not None and target not in TRANSITIONS.get(current, set()):
            raise IndexLifecycleError(f"invalid index transition: {current} -> {target}")
        state = {"runId": run_dir.name, "status": target, "updatedAt": _now(), **(extra or {})}
        _atomic_json(run_dir / "state.json", state)
        if target in ACTIVE_STATES or target == "failed":
            _atomic_json(self.marker_path, state)
        self._audit({"runId": run_dir.name, "status": target})

    def _validate_candidate(self, artifact: Path, resolved: str) -> tuple[dict, str]:
        try:
            data = json.loads(artifact.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IndexLifecycleError("candidate index is absent or invalid JSON") from exc
        if data.get("repoId") != self.manifest.repo_id:
            raise IndexLifecycleError("candidate repository does not match the request")
        if data.get("sourceSha") != resolved:
            raise IndexLifecycleError("candidate commit does not match the requested commit")
        if data.get("schemaVersion") != "1.0":
            raise IndexLifecycleError("candidate schema is incompatible")
        components = data.get("components")
        if not isinstance(components, list):
            raise IndexLifecycleError("candidate components field is invalid")
        for component in components:
            if not isinstance(component, dict) or not isinstance(component.get("path"), str):
                raise IndexLifecycleError("candidate contains an invalid component")
        return data, _sha256(artifact)

    def _snapshot_active(self, run_id: str) -> tuple[str | None, str | None]:
        if not self.active_path.is_file():
            return None, None
        active_hash = _sha256(self.active_path)
        snapshot_id = f"{run_id}-previous"
        target = self.snapshots / snapshot_id
        target.mkdir(parents=True, exist_ok=False)
        shutil.copy2(self.active_path, target / "index.json")
        _atomic_json(target / "manifest.json", {
            "snapshotId": snapshot_id, "artifactSha256": active_hash,
            "createdAt": _now(), "source": "pre-publication",
        })
        return snapshot_id, active_hash

    def publish(
        self, branch: str, requested_commit: str, builder: Callable[[Path, str], None],
        *, operator: str, origin: str = "manual", cancel: Callable[[], bool] | None = None,
        indexer_version: str = "unknown",
    ) -> Publication:
        run_id = uuid.uuid4().hex
        run_dir = self.runs / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        current = None
        fd = self._acquire(run_id)
        previous_index = None
        try:
            resolved = self._resolve_target(branch, requested_commit)
            self._state(run_dir, current, "requested")
            current = "requested"
            if cancel and cancel():
                self._state(run_dir, current, "cancelled")
                raise IndexLifecycleError("indexing was cancelled")
            self._state(run_dir, current, "indexing")
            current = "indexing"
            artifact = run_dir / "candidate" / "index.json"
            artifact.parent.mkdir(parents=True)
            builder(artifact, resolved)
            if cancel and cancel():
                self._state(run_dir, current, "cancelled")
                raise IndexLifecycleError("indexing was cancelled")
            self._state(run_dir, current, "validating")
            current = "validating"
            data, artifact_hash = self._validate_candidate(artifact, resolved)
            previous_index, active_hash = self._snapshot_active(run_id)
            manifest_doc = {
                "repositoryId": self.manifest.repo_id, "branch": branch,
                "requestedCommit": requested_commit, "resolvedCommit": resolved,
                "indexedCommit": data["sourceSha"], "schemaVersion": data["schemaVersion"],
                "indexerVersion": indexer_version, "startedAt": json.loads((run_dir / "state.json").read_text())["updatedAt"],
                "completedAt": _now(), "publishedAt": None,
                "fileCount": len({c["path"] for c in data["components"]}),
                "componentCount": len(data["components"]),
                "includedScopes": list(self.manifest.source_roots),
                "excludedScopes": [".git", "node_modules", ".next", "coverage", "dist", "build", "__pycache__", ".venv", "venv"],
                "artifactSha256": artifact_hash, "status": "ready", "failureReason": None,
                "runId": run_id, "previousIndex": previous_index,
                "operator": operator, "origin": origin,
            }
            manifest_doc["manifestSha256"] = hashlib.sha256(_canonical_json(manifest_doc)).hexdigest()
            _atomic_json(run_dir / "manifest.json", manifest_doc)
            self._state(run_dir, current, "ready")
            current = "ready"
            self._state(run_dir, current, "publishing")
            current = "publishing"
            if active_hash is None:
                if self.active_path.exists():
                    raise IndexLifecycleError("active index changed during publication")
            elif not self.active_path.is_file() or _sha256(self.active_path) != active_hash:
                raise IndexLifecycleError("active index changed during publication")
            self.active_path.parent.mkdir(parents=True, exist_ok=True)
            publish_tmp = self.active_path.with_name(f".{self.active_path.name}.{run_id}.tmp")
            shutil.copy2(artifact, publish_tmp)
            with publish_tmp.open("rb") as stream:
                os.fsync(stream.fileno())
            os.replace(publish_tmp, self.active_path)
            if _sha256(self.active_path) != artifact_hash:
                raise IndexLifecycleError("published index failed integrity verification")
            manifest_doc.update({"status": "published", "publishedAt": _now()})
            manifest_doc.pop("manifestSha256", None)
            manifest_doc["manifestSha256"] = hashlib.sha256(_canonical_json(manifest_doc)).hexdigest()
            _atomic_json(run_dir / "manifest.json", manifest_doc)
            self._state(run_dir, current, "published")
            current = "published"
            try:
                self.marker_path.unlink()
            except FileNotFoundError:
                pass
            return Publication(run_id, current, run_dir / "manifest.json", self.active_path, previous_index)
        except Exception as exc:
            if current not in TERMINAL_STATES:
                try:
                    self._state(run_dir, current, "failed", {"reason": type(exc).__name__})
                except Exception:
                    pass
            if isinstance(exc, IndexLifecycleError):
                raise
            raise IndexLifecycleError("index publication failed") from exc
        finally:
            self._release(fd)

    def rollback(self, snapshot_id: str, *, operator: str, origin: str = "manual") -> Publication:
        if not re.fullmatch(r"[0-9a-f]{32}-previous", snapshot_id):
            raise IndexLifecycleError("snapshot identifier is invalid")
        snapshot_dir = self.snapshots / snapshot_id
        artifact = snapshot_dir / "index.json"
        try:
            metadata = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IndexLifecycleError("snapshot metadata is unavailable") from exc
        if not artifact.is_file() or _sha256(artifact) != metadata.get("artifactSha256"):
            raise IndexLifecycleError("snapshot integrity validation failed")
        run_id = uuid.uuid4().hex
        fd = self._acquire(run_id)
        run_dir = self.runs / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        try:
            temporary = self.active_path.with_name(f".{self.active_path.name}.{run_id}.rollback")
            shutil.copy2(artifact, temporary)
            os.replace(temporary, self.active_path)
            _atomic_json(run_dir / "manifest.json", {
                "runId": run_id, "status": "rolled_back", "snapshotId": snapshot_id,
                "operator": operator, "origin": origin, "completedAt": _now(),
                "artifactSha256": metadata["artifactSha256"],
            })
            _atomic_json(run_dir / "state.json", {"runId": run_id, "status": "rolled_back", "updatedAt": _now()})
            self._audit({"runId": run_id, "status": "rolled_back", "snapshotId": snapshot_id})
            try:
                self.marker_path.unlink()
            except FileNotFoundError:
                pass
            return Publication(run_id, "rolled_back", run_dir / "manifest.json", self.active_path, snapshot_id)
        finally:
            self._release(fd)
