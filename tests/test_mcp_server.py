"""Tests for the architecture-map MCP server tools (issue #31): mcp_server.py
had zero dedicated tests before this -- every other module in the kit
(guard.py, scan/core.py, portfolio.py, verify.py) already had one.

The @mcp.tool()-decorated functions are plain Python functions under the
FastMCP registration -- callable directly without going through the MCP
transport/SDK, same precedent already proven in
test_duplication_golden_corpus.py (which calls check_duplication() this way).

check_duplication() is intentionally not re-tested here: it already has
dedicated coverage in test_duplication_golden_corpus.py. serve() is
intentionally not tested either: it blocks in mcp.run() and has no
behavior of its own beyond load_manifest() (already covered by
tests for aak.manifest) -- an explicit, documented gap, not an oversight.
"""
import json

import pytest

from aak import mcp_server as mcp_server_mod

REPO_ID = "mhx/test-repo"

COMPONENTS = [
    {"path": "src/lib/foo.ts", "exports": ["doThing", "DoThingResult"], "layer": "lib"},
    {"path": "src/services/Bar.ts", "exports": ["bar", "runBar"], "layer": "service"},
]


@pytest.fixture
def mcp_repo(tmp_path, monkeypatch):
    (tmp_path / ".agent-architecture").mkdir()
    (tmp_path / ".agent-architecture" / "project.yaml").write_text(
        f"schemaVersion: \"1.0\"\nrepoId: \"{REPO_ID}\"\ntier: 1\n"
        "defaultBranch: \"main\"\nkitVersion: \"1.0.0\"\n",
        encoding="utf-8",
    )
    arch_dir = tmp_path / "docs" / "architecture"
    arch_dir.mkdir(parents=True)
    (arch_dir / "DUPLICATION_INCIDENTS.json").write_text("[]", encoding="utf-8")
    (arch_dir / "ARCHITECTURE_MAP.json").write_text(json.dumps({
        "schemaVersion": "1.0", "repoId": REPO_ID,
        "generatedAt": "2026-07-29T00:00:00+00:00", "sourceSha": "abc123",
        "extractionMethod": "fixture", "coverage": "fixture",
        "components": COMPONENTS,
    }), encoding="utf-8")

    monkeypatch.setattr(mcp_server_mod, "_manifest", None)
    monkeypatch.setattr(mcp_server_mod, "_repo_root", tmp_path)
    yield tmp_path
    monkeypatch.setattr(mcp_server_mod, "_manifest", None)
    monkeypatch.setattr(mcp_server_mod, "_repo_root", None)


class TestCheckRepoId:
    def test_matching_repo_id_returns_none(self, mcp_repo):
        assert mcp_server_mod._check_repo_id(REPO_ID) is None

    def test_mismatched_repo_id_returns_error(self, mcp_repo):
        result = mcp_server_mod._check_repo_id("wrong/repo")
        assert result is not None
        assert "wrong/repo" in result["error"]
        assert REPO_ID in result["error"]


class TestSearchCapability:
    def test_matches_by_path_substring(self, mcp_repo):
        result = mcp_server_mod.search_capability(REPO_ID, "foo")
        assert [c["path"] for c in result] == ["src/lib/foo.ts"]

    def test_matches_by_export_substring_case_insensitive(self, mcp_repo):
        result = mcp_server_mod.search_capability(REPO_ID, "DOTHING")
        assert [c["path"] for c in result] == ["src/lib/foo.ts"]

    def test_respects_limit(self, mcp_repo):
        result = mcp_server_mod.search_capability(REPO_ID, "src", limit=1)
        assert len(result) == 1

    def test_repo_id_mismatch_returns_single_error_entry(self, mcp_repo):
        result = mcp_server_mod.search_capability("wrong/repo", "foo")
        assert len(result) == 1
        assert "error" in result[0]


class TestGetComponent:
    def test_found(self, mcp_repo):
        result = mcp_server_mod.get_component(REPO_ID, "src/lib/foo.ts")
        assert result == COMPONENTS[0]

    def test_not_found(self, mcp_repo):
        result = mcp_server_mod.get_component(REPO_ID, "src/lib/missing.ts")
        assert "error" in result

    def test_repo_id_mismatch(self, mcp_repo):
        result = mcp_server_mod.get_component("wrong/repo", "src/lib/foo.ts")
        assert "error" in result


class TestAdrs:
    def test_list_adrs_empty_when_dir_missing(self, mcp_repo):
        assert mcp_server_mod.list_adrs() == []

    def test_list_and_get_adr(self, mcp_repo):
        adr_dir = mcp_repo / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "ADR-0001-use-postgres.md").write_text(
            "# ADR 0001: Use Postgres\n\nBecause reasons.\n", encoding="utf-8"
        )
        result = mcp_server_mod.list_adrs()
        assert result == [{
            "slug": "ADR-0001-use-postgres",
            "title": "ADR 0001: Use Postgres",
            "path": "docs/adr/ADR-0001-use-postgres.md",
        }]

        content = mcp_server_mod.get_adr("ADR-0001-use-postgres")
        assert "Because reasons." in content

    def test_get_adr_not_found(self, mcp_repo):
        result = mcp_server_mod.get_adr("does-not-exist")
        assert result.startswith("error:")


class TestMapStatus:
    def test_returns_expected_fields(self, mcp_repo):
        result = mcp_server_mod.get_map_status(REPO_ID)
        assert result["sourceSha"] == "abc123"
        assert result["componentCount"] == 2
        assert result["extractionMethod"] == "fixture"

    def test_repo_id_mismatch(self, mcp_repo):
        result = mcp_server_mod.get_map_status("wrong/repo")
        assert "error" in result


class TestVerifyReferences:
    def test_splits_verified_and_missing(self, mcp_repo):
        result = mcp_server_mod.verify_references(
            REPO_ID,
            paths=["src/lib/foo.ts", "src/lib/nope.ts"],
            symbols=["doThing", "notReal"],
        )
        assert result["verifiedPaths"] == ["src/lib/foo.ts"]
        assert result["missingPaths"] == ["src/lib/nope.ts"]
        assert result["verifiedSymbols"] == ["doThing"]
        assert result["missingSymbols"] == ["notReal"]

    def test_repo_id_mismatch(self, mcp_repo):
        result = mcp_server_mod.verify_references("wrong/repo", paths=[], symbols=[])
        assert "error" in result
