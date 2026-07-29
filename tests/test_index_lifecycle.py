import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from aak.index_lifecycle import IndexLifecycle, IndexLifecycleError
from aak.manifest import ProjectManifest


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
        capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def lifecycle(tmp_path):
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    (tmp_path / "tracked.txt").write_text("fixture", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "fixture"], check=True, capture_output=True)
    manifest = ProjectManifest(
        schema_version="1.0", repo_id="lexnotify/web", tier=1,
        default_branch="main", kit_version="1.0", source_roots=["src"],
        architecture={"map": "docs/architecture/ARCHITECTURE_MAP.json"}, repo_root=tmp_path,
    )
    return IndexLifecycle(tmp_path, manifest), _head(tmp_path)


def _doc(commit: str, path: str = "src/a.ts") -> dict:
    return {
        "schemaVersion": "1.0", "repoId": "lexnotify/web", "sourceSha": commit,
        "generatedAt": "2026-07-29T00:00:00+00:00", "components": [
            {"path": path, "exports": ["A"], "layer": "lib"},
        ],
    }


def _builder(doc: dict):
    def build(path: Path, resolved: str):
        assert resolved == doc["sourceSha"]
        path.write_text(json.dumps(doc), encoding="utf-8")
    return build


def test_publication_is_validated_manifested_and_atomic(lifecycle):
    service, commit = lifecycle
    result = service.publish("main", commit, _builder(_doc(commit)), operator="test", indexer_version="1.2.3")
    assert result.status == "published"
    assert json.loads(service.active_path.read_text())["sourceSha"] == commit
    manifest = json.loads(result.manifest_path.read_text())
    checksum = manifest.pop("manifestSha256")
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    assert checksum == hashlib.sha256(canonical).hexdigest()
    assert manifest["requestedCommit"] == manifest["resolvedCommit"] == manifest["indexedCommit"] == commit
    assert manifest["componentCount"] == manifest["fileCount"] == 1
    assert not service.marker_path.exists()


def test_invalid_candidate_never_replaces_active_index(lifecycle):
    service, commit = lifecycle
    service.active_path.parent.mkdir(parents=True)
    original = json.dumps(_doc(commit, "src/original.ts"))
    service.active_path.write_text(original)

    def broken(path: Path, resolved: str):
        path.write_text("{broken", encoding="utf-8")

    with pytest.raises(IndexLifecycleError, match="invalid JSON"):
        service.publish("main", commit, broken, operator="test")
    assert service.active_path.read_text() == original
    assert json.loads(service.marker_path.read_text())["status"] == "failed"


def test_wrong_commit_or_schema_never_publishes(lifecycle):
    service, commit = lifecycle
    wrong = _doc("0" * 40)
    def wrong_builder(path: Path, resolved: str):
        path.write_text(json.dumps(wrong), encoding="utf-8")
    with pytest.raises(IndexLifecycleError, match="candidate commit"):
        service.publish("main", commit, wrong_builder, operator="test")
    incompatible = _doc(commit)
    incompatible["schemaVersion"] = "2.0"
    with pytest.raises(IndexLifecycleError, match="schema"):
        service.publish("main", commit, _builder(incompatible), operator="test")
    assert not service.active_path.exists()


def test_short_nonexistent_and_other_branch_commits_are_rejected(lifecycle):
    service, commit = lifecycle
    with pytest.raises(IndexLifecycleError, match="40-character"):
        service.publish("main", commit[:8], _builder(_doc(commit)), operator="test")
    with pytest.raises(IndexLifecycleError, match="Git object"):
        service.publish("main", "0" * 40, _builder(_doc(commit)), operator="test")
    subprocess.run(["git", "-C", str(service.repo_root), "switch", "-c", "other"], check=True, capture_output=True)
    (service.repo_root / "other.txt").write_text("other")
    subprocess.run(["git", "-C", str(service.repo_root), "add", "other.txt"], check=True)
    subprocess.run(["git", "-C", str(service.repo_root), "commit", "-m", "other"], check=True, capture_output=True)
    other = _head(service.repo_root)
    subprocess.run(["git", "-C", str(service.repo_root), "switch", "main"], check=True, capture_output=True)
    with pytest.raises(IndexLifecycleError, match="outside"):
        service.publish("main", other, _builder(_doc(other)), operator="test")


def test_lock_prevents_two_publishers(lifecycle):
    service, commit = lifecycle
    service.state_root.mkdir(parents=True)
    service.lock_path.write_text("existing", encoding="utf-8")
    with pytest.raises(IndexLifecycleError, match="holds the lock"):
        service.publish("main", commit, _builder(_doc(commit)), operator="test")


def test_compare_and_swap_detects_active_change(lifecycle, monkeypatch):
    service, commit = lifecycle
    service.active_path.parent.mkdir(parents=True)
    service.active_path.write_text(json.dumps(_doc(commit, "src/original.ts")))
    original_snapshot = service._snapshot_active

    def mutate(run_id):
        result = original_snapshot(run_id)
        service.active_path.write_text(json.dumps(_doc(commit, "src/concurrent.ts")))
        return result

    monkeypatch.setattr(service, "_snapshot_active", mutate)
    with pytest.raises(IndexLifecycleError, match="changed during publication"):
        service.publish("main", commit, _builder(_doc(commit)), operator="test")
    assert json.loads(service.active_path.read_text())["components"][0]["path"] == "src/concurrent.ts"


def test_previous_snapshot_is_preserved_and_rollback_is_atomic(lifecycle):
    service, commit = lifecycle
    service.active_path.parent.mkdir(parents=True)
    previous = _doc(commit, "src/previous.ts")
    service.active_path.write_text(json.dumps(previous))
    publication = service.publish("main", commit, _builder(_doc(commit, "src/current.ts")), operator="test")
    assert publication.previous_index
    rollback = service.rollback(publication.previous_index, operator="test")
    assert rollback.status == "rolled_back"
    assert json.loads(service.active_path.read_text()) == previous
    assert (service.snapshots / publication.previous_index / "index.json").exists()
    assert json.loads(rollback.manifest_path.read_text())["operator"] == "test"


def test_corrupt_snapshot_is_rejected_without_touching_active(lifecycle):
    service, commit = lifecycle
    service.active_path.parent.mkdir(parents=True)
    service.active_path.write_text(json.dumps(_doc(commit, "src/previous.ts")))
    publication = service.publish("main", commit, _builder(_doc(commit)), operator="test")
    snapshot = service.snapshots / publication.previous_index / "index.json"
    snapshot.write_text("tampered", encoding="utf-8")
    active = service.active_path.read_bytes()
    with pytest.raises(IndexLifecycleError, match="integrity"):
        service.rollback(publication.previous_index, operator="test")
    assert service.active_path.read_bytes() == active


def test_cancelled_build_does_not_publish(lifecycle):
    service, commit = lifecycle
    calls = iter([False, True])
    with pytest.raises(IndexLifecycleError, match="cancelled"):
        service.publish("main", commit, _builder(_doc(commit)), operator="test", cancel=lambda: next(calls))
    assert not service.active_path.exists()
    states = [json.loads(path.read_text())["status"] for path in service.runs.glob("*/state.json")]
    assert states == ["cancelled"]


def test_audit_contains_metadata_not_index_content(lifecycle):
    service, commit = lifecycle
    secret_marker = "DO_NOT_LOG_CONTENT"
    doc = _doc(commit, f"src/{secret_marker}.ts")
    service.publish("main", commit, _builder(doc), operator="test")
    audit = service.audit_path.read_text()
    assert secret_marker not in audit
    assert "published" in audit
