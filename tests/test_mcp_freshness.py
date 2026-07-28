import json
import subprocess
from pathlib import Path

import pytest

from aak import mcp_server
from aak.manifest import ProjectManifest


def _manifest(repo: Path) -> ProjectManifest:
    return ProjectManifest(
        schema_version="1.0", repo_id="lexnotify/web", tier=1,
        default_branch="main", kit_version="1.0",
        source_roots=["app", "src"],
        architecture={"map": "docs/architecture/ARCHITECTURE_MAP.json"},
        repo_root=repo,
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    (tmp_path / "tracked.txt").write_text("fixture", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "fixture"], check=True, capture_output=True)
    map_path = tmp_path / "docs/architecture/ARCHITECTURE_MAP.json"
    map_path.parent.mkdir(parents=True)
    monkeypatch.setattr(mcp_server, "_repo_root", tmp_path)
    monkeypatch.setattr(mcp_server, "_manifest", _manifest(tmp_path))
    return tmp_path, map_path


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", name], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", name], check=True, capture_output=True)
    return _head(repo)


def _write_map(path: Path, source_sha: str | None, **overrides):
    doc = {
        "schemaVersion": "1.0", "repoId": "lexnotify/web",
        "generatedAt": "2026-07-28T00:00:00+00:00", "sourceSha": source_sha,
        "extractionMethod": "fixture", "coverage": "fixture",
        "components": [{"path": "src/a.ts", "exports": ["a"], "layer": "lib"}],
    }
    doc.update(overrides)
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_fresh_index_allows_existing_tool_contracts(repo):
    root, map_path = repo
    sha = _head(root)
    _write_map(map_path, sha)
    status = mcp_server.get_map_status("lexnotify/web", sha)
    assert status["freshness"] == "fresh"
    assert status["sourceSha"] == sha
    assert status["expectedCommit"] == sha
    assert status["componentCount"] == 1
    assert mcp_server.search_capability("lexnotify/web", "a", expectedCommit=sha)[0]["path"] == "src/a.ts"
    assert mcp_server.get_component("lexnotify/web", "src/a.ts", sha)["path"] == "src/a.ts"


def test_stale_index_blocks_conclusive_tools(repo):
    root, map_path = repo
    indexed = _head(root)
    expected = _commit(root, "new.txt")
    _write_map(map_path, indexed)
    result = mcp_server.search_capability("lexnotify/web", "a", expectedCommit=expected)
    assert result[0]["error"]["code"] == "INDEX_NOT_FRESH"
    assert result[0]["index"]["freshness"] == "stale"
    assert result[0]["historicalOnly"] is True


@pytest.mark.parametrize("source_sha", [None, "not-a-sha"])
def test_missing_or_invalid_source_sha_is_unknown(repo, source_sha):
    _, map_path = repo
    _write_map(map_path, source_sha)
    assert mcp_server.get_map_status("lexnotify/web")["freshness"] == "unknown"


def test_invalid_expected_sha_is_unknown_and_blocked(repo):
    root, map_path = repo
    _write_map(map_path, _head(root))
    assert mcp_server.get_map_status("lexnotify/web", "bad")["freshness"] == "unknown"
    assert mcp_server.get_component("lexnotify/web", "src/a.ts", "bad")["error"]["code"] == "INDEX_NOT_FRESH"


def test_missing_expected_sha_is_unknown_and_blocks_all_conclusive_tools(repo):
    root, map_path = repo
    _write_map(map_path, _head(root))
    assert mcp_server.get_map_status("lexnotify/web")["freshness"] == "unknown"
    assert mcp_server.search_capability("lexnotify/web", "a")[0]["error"]["code"] == "INDEX_NOT_FRESH"
    assert mcp_server.get_component("lexnotify/web", "src/a.ts")["error"]["code"] == "INDEX_NOT_FRESH"
    assert mcp_server.check_duplication("chat")["error"]["code"] == "INDEX_NOT_FRESH"
    assert mcp_server.list_adrs()[0]["error"]["code"] == "INDEX_NOT_FRESH"
    assert mcp_server.get_adr("decision")["error"]["code"] == "INDEX_NOT_FRESH"
    assert mcp_server.verify_references("lexnotify/web", [], [])["error"]["code"] == "INDEX_NOT_FRESH"


@pytest.mark.parametrize("expected", ["a" * 7, "g" * 40, "A" * 40, "0" * 40])
def test_short_malformed_or_nonexistent_expected_sha_is_unknown(repo, expected):
    root, map_path = repo
    _write_map(map_path, _head(root))
    assert mcp_server.get_map_status("lexnotify/web", expected)["freshness"] == "unknown"


def test_commit_from_another_branch_cannot_be_declared_fresh(repo):
    root, map_path = repo
    main = _head(root)
    subprocess.run(["git", "-C", str(root), "switch", "-c", "other"], check=True, capture_output=True)
    other = _commit(root, "other.txt")
    subprocess.run(["git", "-C", str(root), "switch", "main"], check=True, capture_output=True)
    assert _head(root) == main
    _write_map(map_path, other)
    status = mcp_server.get_map_status("lexnotify/web", other)
    assert status["freshness"] == "unknown"
    assert "outside the served branch history" in status["reason"]


def test_incompatible_schema_is_blocked(repo):
    root, map_path = repo
    _write_map(map_path, _head(root), schemaVersion="2.0")
    assert mcp_server.get_map_status("lexnotify/web")["freshness"] == "incompatible"
    assert mcp_server.verify_references("lexnotify/web", [], [])["error"]["code"] == "INDEX_NOT_FRESH"


def test_indexing_marker_never_replaces_last_valid_index(repo):
    root, map_path = repo
    _write_map(map_path, _head(root))
    map_path.with_suffix(map_path.suffix + ".indexing").write_text(
        json.dumps({"status": "indexing"}), encoding="utf-8",
    )
    assert mcp_server.get_map_status("lexnotify/web")["freshness"] == "indexing"
    assert mcp_server.check_duplication("chat")["error"]["code"] == "INDEX_NOT_FRESH"


def test_backend_unavailable_is_failed(repo):
    _, map_path = repo
    assert not map_path.exists()
    status = mcp_server.get_map_status("lexnotify/web")
    assert status["freshness"] == "failed"
    assert "FileNotFoundError" in status["reason"]
    result = mcp_server.get_component("lexnotify/web", "src/a.ts", _head(repo[0]))
    assert result["error"]["code"] == "INDEX_BACKEND_UNAVAILABLE"


def test_corrupt_indexing_marker_is_failed(repo):
    root, map_path = repo
    _write_map(map_path, _head(root))
    map_path.with_suffix(map_path.suffix + ".indexing").write_text("building", encoding="utf-8")
    status = mcp_server.get_map_status("lexnotify/web", _head(root))
    assert status["freshness"] == "failed"
    assert "invalid" in status["reason"]


def test_repository_mismatch_fails_before_reading_index(repo):
    assert "repoId mismatch" in mcp_server.get_map_status("other/repo")["error"]


def test_repo_metadata_mismatch_is_incompatible(repo):
    root, map_path = repo
    _write_map(map_path, _head(root), repoId="other/repo")
    assert mcp_server.get_map_status("lexnotify/web")["freshness"] == "incompatible"
