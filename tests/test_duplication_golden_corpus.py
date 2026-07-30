"""Golden-corpus replay test (master plan section 12.1/12.4): "the known
case-chat and notification failures are replayed successfully."

Fixture below is a static copy of the two real, verified incidents from
LexNotify/LexNotify-Web:docs/architecture/DUPLICATION_INCIDENTS.json, as
corrected in this session (canonicalTarget/duplicateArtifact previously
pointed at a compat shim and at the wrong layer -- see the companion PR in
that repo). This test does not hit the network; it proves the kit's own
check_duplication() logic actually catches these two known incidents given
correct data, independent of whether that repo's file stays in sync.
"""
import json

import pytest

from aak import mcp_server as mcp_server_mod

INCIDENTS = [
    {
        "date": "2026-07-16",
        "businessTerms": [
            "verticalized chat", "case chat", "process conversation",
            "chat por processo", "chat verticalizado por processo",
        ],
        "duplicateArtifact": "src/components/dashboard/HearingDetailSheet.tsx",
        "canonicalTarget": {"path": "src/domain/cases/case-chat.ts", "symbol": "getOrCreateCaseChat"},
        "evidenceSources": ["commit:5b445d56", "issue:677"],
        "acceptedAliases": ["chat by case", "conversation linked to a lawsuit", "chat verticalizado por processo"],
    },
    {
        "date": "2026-07-16",
        "businessTerms": [
            "notification pipeline", "unified notifications",
            "pipeline de notificacoes", "notification unification",
        ],
        "duplicateArtifact": "src/services/NotificationService.ts",
        "canonicalTarget": {"path": "src/services/EventService.ts", "symbol": "publish"},
        "evidenceSources": ["commit:706dc2077760cd29725c962c23ee227ccab33c69", "issue:594", "issue:552"],
        "acceptedAliases": ["unified notification pipeline", "V2 pipeline", "notification_events pipeline"],
    },
]

class _TrustedGoldenBoundary:
    def authorize(self, **kwargs):
        return None, "golden-correlation", None

    def protect_response(self, value, correlation_id):
        return value


COMPONENTS = [
    {"path": "src/domain/cases/case-chat.ts", "exports": ["getOrCreateCaseChat", "CaseChatRef"], "layer": "domain"},
    {"path": "src/lib/process-chat.ts", "exports": ["openProcessChat", "buildProcessChatHref"], "layer": "lib"},
    # publish/processPendingNotifications are class methods, not top-level
    # exports (only the instance -- eventService/notificationService -- is
    # exported). Fixed in issue #35: the TypeScript adapter now also records
    # public class-method names as bare export entries even when only an
    # instance of the class is exported, so canonicalTarget.symbol: "publish"
    # (the method a caller actually invokes) is verifiable like any other
    # symbol -- confirmed against the real ARCHITECTURE_MAP.json.
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
        "repoId: \"LexNotify/LexNotify-Web\"\n"
        "tier: 1\n"
        "defaultBranch: \"main\"\n"
        "kitVersion: \"1.0.0\"\n",
        encoding="utf-8",
    )
    arch_dir = tmp_path / "docs" / "architecture"
    arch_dir.mkdir(parents=True)
    (arch_dir / "DUPLICATION_INCIDENTS.json").write_text(json.dumps(INCIDENTS), encoding="utf-8")
    (arch_dir / "ARCHITECTURE_MAP.json").write_text(json.dumps({
        "schemaVersion": "1.0", "repoId": "LexNotify/LexNotify-Web",
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


def test_replays_case_chat_incident(golden_repo):
    _, expected_commit = golden_repo
    result = mcp_server_mod.check_duplication(
        "preciso implementar chat verticalizado por processo pra nova tela de audiencias",
        expectedCommit=expected_commit,
    )
    assert result["matchedIncident"] is not None
    assert result["matchedIncident"]["canonicalTarget"] == {
        "path": "src/domain/cases/case-chat.ts", "symbol": "getOrCreateCaseChat",
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


def test_case_chat_candidate_components_surface_both_canonical_symbols(golden_repo):
    """The fix for the case-chat incident introduced two canonical symbols
    (getOrCreateCaseChat for provisioning, openProcessChat for navigation) --
    a search for "chat" should surface both, not just one."""
    _, expected_commit = golden_repo
    result = mcp_server_mod.check_duplication(
        "preciso implementar chat verticalizado por processo",
        expectedCommit=expected_commit,
    )
    candidate_paths = {c["path"] for c in result["candidateComponents"]}
    assert "src/domain/cases/case-chat.ts" in candidate_paths
    assert "src/lib/process-chat.ts" in candidate_paths


def test_notification_incident_canonical_symbol_now_verifiable(golden_repo):
    """Regression guard for issue #35: verify_references used to report
    "publish" as a missingSymbol even though it's the correct, human-verified
    canonicalTarget.symbol -- a scanner coverage gap, not a bad citation."""
    monkeypatch_manifest = mcp_server_mod._get_manifest()
    result = mcp_server_mod.verify_references(
        repoId=monkeypatch_manifest.repo_id,
        paths=["src/services/EventService.ts"],
        symbols=["publish", "processPendingNotifications"],
    )
    assert result["missingSymbols"] == []
    assert set(result["verifiedSymbols"]) == {"publish", "processPendingNotifications"}
