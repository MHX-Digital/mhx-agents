"""Canaries use only disposable, fictional Git commits and the real gate CLI."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

GATE = Path(__file__).resolve().parents[1] / "scripts/ci/check_whitespace.py"


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "Fictional fixture")
    git(tmp_path, "config", "user.email", "fixture@example.invalid")
    return tmp_path


def commit(repo, value):
    (repo / "example.txt").write_text(value)
    git(repo, "add", ".")
    git(repo, "commit", "-m", "fictional gate fixture")
    return git(repo, "rev-parse", "HEAD")


def gate(repo, base=""):
    return subprocess.run([sys.executable, str(GATE), "--repo-root", str(repo), "--base", base],
                          capture_output=True, text=True, timeout=15).returncode


@pytest.mark.parametrize("bad", [False, True])
def test_manual_root_and_parent_reject_real_bad_diff(repo, bad):
    commit(repo, "first  \n" if bad else "first\n")
    assert (gate(repo) != 0) == bad
    commit(repo, "second  \n" if bad else "second\n")
    assert (gate(repo) != 0) == bad


def test_pr_checks_final_diff_instead_of_corrected_history(repo):
    base = commit(repo, "first\n")
    commit(repo, "bad intermediate  \n")
    assert gate(repo, base) != 0
    commit(repo, "fixed final\n")
    assert gate(repo, base) == 0


def test_invalid_and_missing_base_fail(repo):
    commit(repo, "fixture\n")
    assert gate(repo, "not-a-sha") != 0
    assert gate(repo, "0" * 40) != 0
