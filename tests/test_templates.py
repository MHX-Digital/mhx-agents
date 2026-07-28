"""Syntax validation for every YAML/JSON file under templates/.

Deliberately uses os.walk instead of glob/Path.rglob: both of those exclude
directories and files starting with "." by default under a "*" wildcard, so
a naive glob("templates/**/*.json") silently never checks
templates/repository/.claude/settings.json or .mcp.example.json -- exactly
the two files where a syntax error would matter most (real hook wiring).
os.walk has no such exclusion, so it actually finds them.
"""
import json
import os

import pytest
import yaml

from aak.paths import KIT_ROOT

TEMPLATES_DIR = KIT_ROOT / "templates"


def _walk_by_suffix(suffixes: tuple[str, ...]) -> list[str]:
    found = []
    for root, _dirs, files in os.walk(TEMPLATES_DIR):
        for name in files:
            if name.endswith(suffixes):
                found.append(os.path.join(root, name))
    return found


YAML_FILES = _walk_by_suffix((".yml", ".yaml"))
JSON_FILES = _walk_by_suffix((".json",))


def test_walk_finds_dotfile_configs():
    """Guards the os.walk-not-glob premise above: if this ever regresses to
    missing the dotfiles, every other test in this file would be silently
    testing less than it claims to."""
    names = {os.path.basename(f) for f in JSON_FILES}
    assert "settings.json" in names
    assert ".mcp.example.json" in names


@pytest.mark.parametrize("path", YAML_FILES)
def test_yaml_file_parses(path):
    with open(path, encoding="utf-8") as f:
        yaml.safe_load(f)


@pytest.mark.parametrize("path", JSON_FILES)
def test_json_file_parses(path):
    with open(path, encoding="utf-8") as f:
        json.load(f)
