"""Tests for aak.verify.run_verify: composes manifest/map schema validation,
optional drift check, and optional staged scope-check into one gate."""
import json
import subprocess
from pathlib import Path

import pytest

from aak.verify import run_verify

MANIFEST_YAML = """\
schemaVersion: "1.0"
repoId: "test/repo"
tier: 1
defaultBranch: "main"
kitVersion: "1.0.0"
sourceRoots: ["src"]
protectedDomains: []
generatedPaths: []
"""


def _init_repo(tmp_path: Path) -> Path:
    (tmp_path / ".agent-architecture").mkdir()
    (tmp_path / ".agent-architecture" / "project.yaml").write_text(MANIFEST_YAML, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def test_run_verify_fails_closed_without_manifest(tmp_path):
    checks, code = run_verify(tmp_path, language=None, staged=False)
    assert code == 1
    assert any(not c.passed and "manifest" in c.name for c in checks)


def test_run_verify_passes_with_minimal_valid_repo(tmp_path):
    repo = _init_repo(tmp_path)
    checks, code = run_verify(repo, language=None, staged=False)
    assert code == 0
    by_name = {c.name: c for c in checks}
    assert by_name["architecture-schema:manifest"].passed
    assert by_name["architecture-schema:map"].passed
    assert "not generated yet" in by_name["architecture-schema:map"].detail
    assert by_name["architecture-drift"].passed
    assert "skipped: no --language given" in by_name["architecture-drift"].detail
    assert by_name["scope-verification"].passed
    assert "skipped: --staged not passed" in by_name["scope-verification"].detail


def test_run_verify_rejects_invalid_map_schema(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "docs" / "architecture").mkdir(parents=True)
    (repo / "docs" / "architecture" / "ARCHITECTURE_MAP.json").write_text(
        json.dumps({"schemaVersion": "1.0"}), encoding="utf-8"
    )
    checks, code = run_verify(repo, language=None, staged=False)
    assert code == 1
    by_name = {c.name: c for c in checks}
    assert not by_name["architecture-schema:map"].passed


def test_run_verify_drift_check_fails_when_map_missing_but_language_given(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("def foo(): pass\n", encoding="utf-8")
    checks, code = run_verify(repo, language="python", staged=False)
    assert code == 1
    by_name = {c.name: c for c in checks}
    assert not by_name["architecture-drift"].passed
    assert "DRIFT" in by_name["architecture-drift"].detail


def test_run_verify_staged_scope_check_denies_protected_domain_without_decision(tmp_path):
    manifest_with_domain = MANIFEST_YAML.replace('protectedDomains: []', 'protectedDomains: ["chat"]')
    (tmp_path / ".agent-architecture").mkdir()
    (tmp_path / ".agent-architecture" / "project.yaml").write_text(manifest_with_domain, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "chat").mkdir()
    (tmp_path / "src" / "chat" / "new.ts").write_text("export const x = 1;\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/chat/new.ts"], cwd=tmp_path, check=True)

    checks, code = run_verify(tmp_path, language=None, staged=True)
    assert code == 1
    by_name = {c.name: c for c in checks}
    assert not by_name["scope-verification"].passed
