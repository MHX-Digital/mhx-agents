"""Synthetic duplication incidents: canonical reuse, nonmatch, and symbol coverage.

All paths, dates, identities and source labels below are fictional. These tests
preserve correlation assertions without depending on any external project.
"""
import json

import pytest

from aak import mcp_server as mcp_server_mod

INCIDENTS = [
    {
        "date": "2026-01-01",
        "businessTerms": [
            "workspace chat", "team chat", "workspace conversation",
            "chat by workspace", "workspace chat",
        ],
        "duplicateArtifact": "src/components/WorkspacePanel.tsx",
        "canonicalTarget": {"path": "src/domain/chat/workspace-chat.ts", "symbol": "getOrCreateWorkspaceChat"},
        "evidenceSources": ["fixture:chat-source", "fixture:chat-review"],
        "acceptedAliases": ["team conversation", "conversation linked to a workspace", "workspace chat"],
    },
    {
        "date": "2026-01-01",
        "businessTerms": [
            "notification pipeline", "unified notifications",
            "pipeline de notificacoes", "notification unification",
        ],
        "duplicateArtifact": "src/services/NotificationService.ts",
        "canonicalTarget": {"path": "src/services/EventService.ts", "symbol": "publish"},
        "evidenceSources": ["fixture:notification-source", "fixture:notification-review", "fixture:delivery-review"],
        "acceptedAliases": ["unified notification pipeline", "V2 pipeline", "notification_events pipeline"],
    },
]

class _TrustedGoldenBoundary:
    def authorize(self, **kwargs):
        return None, "golden-correlation", None

    def protect_response(self, value, correlation_id):
        return value


COMPONENTS = [
    {"path": "src/domain/chat/workspace-chat.ts", "exports": ["getOrCreateWorkspaceChat", "WorkspaceChatRef"], "layer": "domain"},
    {"path": "src/lib/workspace-chat.ts", "exports": ["openWorkspaceChat", "buildWorkspaceChatHref"], "layer": "lib"},
    # publish/processPendingNotifications are class methods, not top-level
    # exports (only the instance -- eventService/notificationService -- is
    # exported). Fixed in issue #35: the TypeScript adapter now also records
    # public class-method names as bare export entries even when only an
    # instance of the class is exported, so canonicalTarget.symbol: "publish"
    # (the method a caller actually invokes) is verifiable like any other
    # symbol -- confirmed against the synthetic architecture map.
    {"path": "src/services/EventService.ts", "exports": ["eventService", "publish"], "layer": "service"},
    {
        "path": "src/services/NotificationService.ts",
        "exports": ["notificationService", "processPendingNotifications"],
        "layer": "service",
    },
]


@pytest.fixture
def golden_repo(tmp_path, monkeypatch):
    (tmp_path / ".agent-architecture").mkdir()
    (tmp_path / ".agent-architecture" / "project.yaml").write_text(
        "schemaVersion: \"1.0\"\n"
        "repoId: \"example/catalog\"\n"
        "tier: 1\n"
        "defaultBranch: \"main\"\n"
        "kitVersion: \"1.0.0\"\n",
        encoding="utf-8",
    )
    arch_dir = tmp_path / "docs" / "architecture"
    arch_dir.mkdir(parents=True)
    (arch_dir / "DUPLICATION_INCIDENTS.json").write_text(json.dumps(INCIDENTS), encoding="utf-8")
    (arch_dir / "ARCHITECTURE_MAP.json").write_text(json.dumps({
        "schemaVersion": "1.0", "repoId": "example/catalog",
        "generatedAt": "2026-07-28T00:00:00+00:00", "sourceSha": "fixture",
        "extractionMethod": "fixture", "coverage": "fixture",
        "components": COMPONENTS,
    }), encoding="utf-8")

    monkeypatch.setattr(mcp_server_mod, "_manifest", None)
    monkeypatch.setattr(mcp_server_mod, "_repo_root", tmp_path)
    monkeypatch.setattr(mcp_server_mod, "_security", _TrustedGoldenBoundary())
    expected_commit = "a" * 40

    def require_expected_commit(value):
        assert value == expected_commit
        return None

    monkeypatch.setattr(mcp_server_mod, "_freshness_error", require_expected_commit)
    yield tmp_path, expected_commit
    monkeypatch.setattr(mcp_server_mod, "_manifest", None)
    monkeypatch.setattr(mcp_server_mod, "_repo_root", None)


def test_replays_workspace_chat_incident(golden_repo):
    _, expected_commit = golden_repo
    result = mcp_server_mod.check_duplication(
        "please add workspace chat to the team screen",
        expectedCommit=expected_commit,
    )
    assert result["matchedIncident"] is not None
    assert result["matchedIncident"]["canonicalTarget"] == {
        "path": "src/domain/chat/workspace-chat.ts", "symbol": "getOrCreateWorkspaceChat",
    }


def test_replays_notification_pipeline_incident(golden_repo):
    _, expected_commit = golden_repo
    result = mcp_server_mod.check_duplication(
        "vou mexer no pipeline de notificacoes pra adicionar um canal novo de SMS",
        expectedCommit=expected_commit,
    )
    assert result["matchedIncident"] is not None
    assert result["matchedIncident"]["canonicalTarget"] == {
        "path": "src/services/EventService.ts", "symbol": "publish",
    }


def test_unrelated_request_matches_no_incident(golden_repo):
    _, expected_commit = golden_repo
    result = mcp_server_mod.check_duplication(
        "quero adicionar um botao de exportar CSV na tela de relatorios",
        expectedCommit=expected_commit,
    )
    assert result["matchedIncident"] is None


def test_workspace_chat_candidate_components_surface_both_canonical_symbols(golden_repo):
    """The fix for the workspace-chat incident introduced two canonical symbols
    (getOrCreateWorkspaceChat for provisioning, openWorkspaceChat for navigation) --
    a search for "chat" should surface both, not just one."""
    _, expected_commit = golden_repo
    result = mcp_server_mod.check_duplication(
        "please implement workspace chat",
        expectedCommit=expected_commit,
    )
    candidate_paths = {c["path"] for c in result["candidateComponents"]}
    assert "src/domain/chat/workspace-chat.ts" in candidate_paths
    assert "src/lib/workspace-chat.ts" in candidate_paths


def test_notification_incident_canonical_symbol_now_verifiable(golden_repo):
    """Regression guard for issue #35: verify_references used to report
    "publish" as a missingSymbol even though it's the fixture-defined
    canonicalTarget.symbol -- a scanner coverage gap, not a bad citation."""
    _, expected_commit = golden_repo
    monkeypatch_manifest = mcp_server_mod._get_manifest()
    result = mcp_server_mod.verify_references(
        repoId=monkeypatch_manifest.repo_id,
        paths=["src/services/EventService.ts"],
        symbols=["publish", "processPendingNotifications"],
        expectedCommit=expected_commit,
    )
    assert result["missingSymbols"] == []
    assert set(result["verifiedSymbols"]) == {"publish", "processPendingNotifications"}
