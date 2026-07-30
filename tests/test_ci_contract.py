from pathlib import Path


WORKFLOW = Path(".github/workflows/mcp-release-gates.yml")


def test_release_workflow_has_minimal_permissions_and_pinned_actions():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in content
    assert "cancel-in-progress: true" in content
    assert content.count("timeout-minutes:") == 2
    for line in content.splitlines():
        if "uses: actions/" in line:
            ref = line.rsplit("@", 1)[-1]
            assert len(ref) == 40
            assert all(char in "0123456789abcdef" for char in ref)


def test_release_workflow_runs_every_critical_suite_and_security_gate():
    content = WORKFLOW.read_text(encoding="utf-8")
    required = {
        "tests/test_mcp_freshness.py",
        "tests/test_index_lifecycle.py",
        "tests/test_mcp_security.py",
        "tests/test_mcp_integrated_resilience.py",
        "python scripts/ci/check_secrets.py",
        "python -m pip_audit --strict",
        "git diff --check",
        "python -m pytest -q --junitxml",
    }
    assert not (required - set(fragment for fragment in required if fragment in content))
    assert "git log --check" not in content


def test_release_workflow_does_not_persist_credentials_or_enable_cache():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert content.count("persist-credentials: false") == 2
    assert content.count('cache: ""') == 2
    assert "pull_request_target" not in content
    assert "${{ secrets." not in content
