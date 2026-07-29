"""Tests for aak.portfolio (deterministic tier-scored portfolio scan)."""
import subprocess

from aak.portfolio import _git_last_commit_at, scan_portfolio, score_project


def _init_git_repo(path, commit_date=None):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("hi")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    env = None
    if commit_date is not None:
        import os

        env = {**os.environ, "GIT_AUTHOR_DATE": commit_date, "GIT_COMMITTER_DATE": commit_date}
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True, env=env)


def test_bare_directory_scores_zero(tmp_path):
    proj = tmp_path / "empty-proj"
    proj.mkdir()
    result = score_project(proj)
    assert result.score == 0
    assert result.language == "unknown"
    assert all(v is False for v in result.signals.values())


def test_all_signals_present_scores_100(tmp_path):
    proj = tmp_path / "full-proj"
    proj.mkdir()
    (proj / "Cargo.toml").write_text("[package]\nname='x'")
    (proj / ".agent-architecture").mkdir()
    (proj / ".agent-architecture" / "project.yaml").write_text("repoId: x")
    (proj / "docs" / "adr").mkdir(parents=True)
    (proj / "tests").mkdir()
    (proj / ".github" / "workflows").mkdir(parents=True)
    (proj / ".github" / "workflows" / "ci.yml").write_text("name: CI")
    _init_git_repo(proj)

    result = score_project(proj)
    assert result.language == "Rust"
    assert result.score == 100
    assert all(result.signals.values())


def test_language_detection_priority_order(tmp_path):
    proj = tmp_path / "multi-lang"
    proj.mkdir()
    (proj / "pubspec.yaml").write_text("name: x")
    (proj / "package.json").write_text("{}")
    # pubspec.yaml (Dart/Flutter) comes before package.json in LANGUAGE_MARKERS
    result = score_project(proj)
    assert result.language == "Dart/Flutter"


def test_python_convention_test_files_without_tests_dir(tmp_path):
    proj = tmp_path / "py-proj"
    proj.mkdir()
    (proj / "requirements.txt").write_text("pytest")
    (proj / "test_foo.py").write_text("def test_x(): pass")
    result = score_project(proj)
    assert result.language == "Python"
    assert result.signals["tests"] is True


def test_scan_portfolio_skips_hidden_and_non_dirs(tmp_path):
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "real-project").mkdir()
    (tmp_path / "a-file.txt").write_text("x")

    results = scan_portfolio(tmp_path)
    names = {r.name for r in results}
    assert names == {"real-project"}


def test_scan_portfolio_nonexistent_root_returns_empty():
    from pathlib import Path

    assert scan_portfolio(Path("/does/not/exist/at/all")) == []


def test_old_commit_does_not_count_as_recent(tmp_path):
    proj = tmp_path / "stale-proj"
    proj.mkdir()
    _init_git_repo(proj, commit_date="2020-01-01T00:00:00+00:00")
    result = score_project(proj)
    assert result.signals["recentCommit"] is False


def test_fresh_commit_counts_as_recent(tmp_path):
    proj = tmp_path / "fresh-proj"
    proj.mkdir()
    _init_git_repo(proj)
    result = score_project(proj)
    assert result.signals["recentCommit"] is True


def test_git_timestamp_z_suffix_is_supported_on_python_310(tmp_path, monkeypatch):
    repo = tmp_path / "z-repo"
    (repo / ".git").mkdir(parents=True)

    class Result:
        returncode = 0
        stdout = "2026-07-29T17:50:00Z\n"

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Result())
    parsed = _git_last_commit_at(repo)
    assert parsed is not None
    assert parsed.isoformat() == "2026-07-29T17:50:00+00:00"
