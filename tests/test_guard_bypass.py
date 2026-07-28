"""Automated bypass corpus for guard.evaluate()'s shell-command deny logic.

Runs through guard.evaluate() end-to-end (client adapter -> DANGEROUS_SHELL_RE /
SELF_GRANT_SHELL_RE), not just the regexes in isolation, so a future refactor of
the shell-kind branch stays covered too. Previously this was only exercised
manually, once, live.
"""
from pathlib import Path

import pytest
import yaml

from aak import guard

MANIFEST = {
    "schemaVersion": "1",
    "repoId": "test-repo",
    "tier": 1,
    "defaultBranch": "main",
    "kitVersion": "0.1.0",
}


@pytest.fixture
def repo_root(tmp_path):
    manifest_dir = tmp_path / ".agent-architecture"
    manifest_dir.mkdir()
    (manifest_dir / "project.yaml").write_text(yaml.safe_dump(MANIFEST))
    return tmp_path


def _evaluate_shell(root: Path, command: str):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    return guard.evaluate("claude", payload, root)


# Real bypass techniques the guard's DANGEROUS_SHELL_RE is meant to catch:
# writing to a file through something other than a Write/Edit tool call.
DENIED_COMMANDS = [
    "tee out.txt",
    "echo x | tee -a out.txt",
    "sed -i 's/x/y/' f.ts",
    "cp a.ts b.ts",
    "mv a.ts b.ts",
    "git apply patch.diff",
    "Set-Content -Path f.txt -Value x",
    "Add-Content -Path f.txt -Value x",
    "Out-File -FilePath f.txt",
    "echo x > f.txt",
    "echo x >> f.txt",
]


@pytest.mark.parametrize("command", DENIED_COMMANDS)
def test_bypass_patterns_are_denied(repo_root, command):
    result = _evaluate_shell(repo_root, command)
    assert not result.allowed, f"expected deny for {command!r} (got: {result.reason})"


# Known false positives, already found live and documented in guard.py's
# DANGEROUS_SHELL_PATTERNS comment (2>&1 etc) - these must stay allowed.
SAFE_COMMANDS = [
    "ls -la 2>&1",
    "npm test 2>&1",
    "some-command >&2",
    "some-command >/dev/null",
    "some-command > /dev/null 2>&1",
    "grep -rn foo . 2>&1 | head -20",
]


@pytest.mark.parametrize("command", SAFE_COMMANDS)
def test_known_false_positives_are_allowed(repo_root, command):
    result = _evaluate_shell(repo_root, command)
    assert result.allowed, f"expected allow for {command!r} (got: {result.reason})"


# Section 5.7: an agent must not be able to self-grant the authority the guard
# checks against by shelling out to the kit's own write commands.
SELF_GRANT_COMMANDS = [
    "aak task start --issue 123",
    "aak override create --issue 123 --scope src/foo",
]


@pytest.mark.parametrize("command", SELF_GRANT_COMMANDS)
def test_self_grant_commands_are_denied(repo_root, command):
    result = _evaluate_shell(repo_root, command)
    assert not result.allowed, f"expected deny (self-grant) for {command!r}"
