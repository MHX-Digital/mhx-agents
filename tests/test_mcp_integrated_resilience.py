import errno
import inspect
import json
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from aak import index_lifecycle, mcp_server
from aak.index_lifecycle import IndexLifecycle, IndexLifecycleError
from aak.manifest import ProjectManifest
from aak.security import SecurityBoundary, issue_token

KEY = b"integrated-test-key-not-a-real-secret"
NOW = 1_800_000_000
TOOLS = {"search_capability", "get_component", "check_duplication", "list_adrs", "get_adr", "get_map_status", "verify_references"}


def _head(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name)
    subprocess.run(["git", "-C", str(repo), "add", name], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", name], check=True, capture_output=True)
    return _head(repo)


def _manifest(repo: Path) -> ProjectManifest:
    return ProjectManifest(
        schema_version="1.0", repo_id="lexnotify/web", tier=1,
        default_branch="main", kit_version="1.0", source_roots=["src"],
        architecture={"map": "docs/architecture/ARCHITECTURE_MAP.json", "adrs": "docs/adr"}, repo_root=repo,
    )


def _doc(commit: str, component="src/a.ts", **overrides):
    doc = {"schemaVersion": "1.0", "repoId": "lexnotify/web", "sourceSha": commit,
           "generatedAt": "2026-07-29T00:00:00Z",
           "components": [{"path": component, "exports": ["A"], "layer": "lib"}]}
    doc.update(overrides)
    return doc


def _token(tenant="avancard-fenix", project="lexnotify/web", tools=TOOLS, jti="integrated"):
    return issue_token("test", KEY, {"sub": "integration", "project": project, "tenant": tenant,
        "role": "auditor", "tools": sorted(tools), "exp": NOW + 3600, "jti": jti})


@pytest.fixture
def integrated(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    (tmp_path / "tracked.txt").write_text("fixture")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "fixture"], check=True, capture_output=True)
    sha = _head(tmp_path)
    manifest = _manifest(tmp_path)
    manifest.map_path.parent.mkdir(parents=True)
    manifest.map_path.write_text(json.dumps(_doc(sha)))
    boundary = SecurityBoundary({"test": KEY}, clock=lambda: NOW, rate_limit=100_000)
    monkeypatch.setattr(mcp_server, "_repo_root", tmp_path)
    monkeypatch.setattr(mcp_server, "_manifest", manifest)
    monkeypatch.setattr(mcp_server, "_security", boundary)
    return tmp_path, sha, manifest, boundary


def _status(sha, token, tenant="avancard-fenix"):
    return mcp_server.get_map_status("lexnotify/web", sha, tenantId=tenant, authToken=token)


def _component(sha, token, tenant="avancard-fenix"):
    return mcp_server.get_component("lexnotify/web", "src/a.ts", sha, tenantId=tenant, authToken=token)


def test_combined_auth_and_freshness_matrix_does_not_leak(integrated):
    repo, indexed, manifest, _ = integrated
    token = _token()
    assert _component(indexed, token)["path"] == "src/a.ts"
    expected = _commit(repo, "new.txt")
    stale = _component(expected, token)
    assert stale["error"]["code"] == "INDEX_NOT_FRESH"
    denied_fresh = _component(indexed, _token(project="other", jti="p"))
    denied_stale = _component(expected, _token(tenant="other", jti="t"))
    for denied in (denied_fresh, denied_stale):
        assert denied["error"]["code"] == "AUTHORIZATION_DENIED"
        assert indexed not in json.dumps(denied) and expected not in json.dumps(denied)


def test_indexing_blocks_conclusions_but_keeps_previous_index(integrated):
    repo, sha, manifest, _ = integrated
    lifecycle = IndexLifecycle(repo, manifest)
    started = threading.Event()
    release = threading.Event()

    def builder(path, resolved, workspace):
        started.set()
        assert release.wait(5)
        path.write_text(json.dumps(_doc(resolved, "src/new.ts")))

    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(lifecycle.publish, "main", sha, builder, operator="test")
        assert started.wait(5)
        status = _status(sha, _token(jti="status"))
        blocked = _component(sha, _token(jti="query"))
        assert status["freshness"] == "indexing"
        assert blocked["error"]["code"] == "INDEX_NOT_FRESH"
        assert json.loads(manifest.map_path.read_text())["components"][0]["path"] == "src/a.ts"
        release.set()
        assert future.result(timeout=10).status == "published"
    assert json.loads(manifest.map_path.read_text())["components"][0]["path"] == "src/new.ts"


def test_failed_publication_restores_previous_readable_index(integrated, monkeypatch):
    repo, sha, manifest, _ = integrated
    lifecycle = IndexLifecycle(repo, manifest)
    original = manifest.map_path.read_bytes()
    real_replace = index_lifecycle.os.replace

    def fail_publication(source, target):
        if Path(target) == lifecycle.active_path and str(source).endswith(".tmp"):
            raise OSError(errno.EIO, "simulated publication failure")
        return real_replace(source, target)

    monkeypatch.setattr(index_lifecycle.os, "replace", fail_publication)
    with pytest.raises(IndexLifecycleError):
        lifecycle.publish("main", sha, lambda p, r, w: p.write_text(json.dumps(_doc(r))), operator="test")
    assert manifest.map_path.read_bytes() == original
    assert json.loads(lifecycle.marker_path.read_text())["status"] == "failed"


def test_disk_full_before_swap_never_replaces_active(integrated, monkeypatch):
    repo, sha, manifest, _ = integrated
    lifecycle = IndexLifecycle(repo, manifest)
    original = manifest.map_path.read_bytes()
    real_copy = index_lifecycle.shutil.copy2

    def no_space(source, target, *args, **kwargs):
        if Path(target).name.startswith(f".{lifecycle.active_path.name}."):
            raise OSError(errno.ENOSPC, "simulated disk full")
        return real_copy(source, target, *args, **kwargs)

    monkeypatch.setattr(index_lifecycle.shutil, "copy2", no_space)
    with pytest.raises(IndexLifecycleError):
        lifecycle.publish("main", sha, lambda p, r, w: p.write_text(json.dumps(_doc(r))), operator="test")
    assert manifest.map_path.read_bytes() == original


def test_atomic_replace_never_exposes_partial_json(integrated):
    repo, sha, manifest, _ = integrated
    lifecycle = IndexLifecycle(repo, manifest)
    errors = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                json.loads(manifest.map_path.read_text())
            except Exception as exc:
                errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(8)]
    for thread in threads:
        thread.start()
    try:
        lifecycle.publish("main", sha, lambda p, r, w: p.write_text(json.dumps(_doc(r, "src/new.ts"))), operator="test")
    finally:
        stop.set()
        for thread in threads:
            thread.join()
    assert errors == []


def test_rollback_and_corrupt_snapshot_behavior(integrated):
    repo, sha, manifest, _ = integrated
    lifecycle = IndexLifecycle(repo, manifest)
    previous = manifest.map_path.read_bytes()
    publication = lifecycle.publish("main", sha, lambda p, r, w: p.write_text(json.dumps(_doc(r, "src/new.ts"))), operator="test")
    assert lifecycle.rollback(publication.previous_index, operator="test").status == "rolled_back"
    assert manifest.map_path.read_bytes() == previous
    snapshot = lifecycle.snapshots / publication.previous_index / "index.json"
    snapshot.write_text("corrupt")
    with pytest.raises(IndexLifecycleError, match="integrity"):
        lifecycle.rollback(publication.previous_index, operator="test")


def test_backend_marker_schema_and_timeout_fail_closed(integrated, monkeypatch):
    repo, sha, manifest, _ = integrated
    token = _token(jti="failures")
    manifest.map_path.unlink()
    assert _status(sha, token)["freshness"] == "failed"
    manifest.map_path.write_text(json.dumps(_doc(sha, schemaVersion="2.0")))
    assert _status(sha, token)["freshness"] == "incompatible"
    manifest.map_path.with_suffix(manifest.map_path.suffix + ".indexing").write_text("corrupt")
    assert _status(sha, token)["freshness"] == "failed"
    manifest.map_path.with_suffix(manifest.map_path.suffix + ".indexing").unlink()
    monkeypatch.setattr(mcp_server, "_read_map", lambda: (_ for _ in ()).throw(TimeoutError()))
    assert _status(sha, token)["freshness"] == "failed"


def test_current_tool_contracts_keep_names_and_optional_compatibility_parameters():
    expected = {"search_capability", "get_component", "check_duplication", "list_adrs", "get_adr", "get_map_status", "verify_references"}
    for name in expected:
        signature = inspect.signature(getattr(mcp_server, name))
        assert "expectedCommit" in signature.parameters
        assert "tenantId" in signature.parameters
        assert "authToken" in signature.parameters
        assert "correlationId" in signature.parameters
    assert expected == TOOLS


def test_concurrent_authorized_queries_are_isolated(integrated):
    _, sha, _, _ = integrated
    def query(index):
        tenant = "avancard-fenix" if index % 2 == 0 else "other"
        token_tenant = tenant if index % 4 != 3 else "avancard-fenix"
        return _status(sha, _token(tenant=token_tenant, jti=f"load-{index}"), tenant=tenant)
    with ThreadPoolExecutor(max_workers=32) as pool:
        results = list(pool.map(query, range(500)))
    allowed = sum(result.get("freshness") == "fresh" for result in results)
    denied = sum(result.get("error", {}).get("code") == "AUTHORIZATION_DENIED" for result in results)
    assert allowed == 375 and denied == 125
