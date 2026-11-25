"""Portfolio inventory with deterministic tier scoring for a selected directory.

The caller explicitly selects the directory; no host or organization inventory
is assumed by the package.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

LANGUAGE_MARKERS = [
    ("Cargo.toml", "Rust"),
    ("pubspec.yaml", "Dart/Flutter"),
    ("Anchor.toml", "Rust/Anchor"),
    ("requirements.txt", "Python"),
    ("pyproject.toml", "Python"),
    ("package.json", "TypeScript/JavaScript"),
    ("go.mod", "Go"),
]

DOC_DIR_NAMES = ("adr", "adrs")
TEST_DIR_NAMES = ("tests", "test", "__tests__")
SCORE_WEIGHT = 20
RECENT_COMMIT_DAYS = 30


def _detect_language(path: Path) -> str:
    for marker, label in LANGUAGE_MARKERS:
        if (path / marker).is_file():
            return label
    return "unknown"


def _has_aak_manifest(path: Path) -> bool:
    return (path / ".agent-architecture" / "project.yaml").is_file()


def _has_structured_docs(path: Path) -> bool:
    docs = path / "docs"
    if any((docs / name).is_dir() for name in DOC_DIR_NAMES):
        return True
    candidates = [
        docs / "ARCHITECTURE_MAP.md",
        path / "ARCHITECTURE.md",
        path / "ARCHITECTURE_OVERVIEW.md",
    ]
    return any(c.is_file() for c in candidates)


def _has_tests(path: Path) -> bool:
    if any((path / name).is_dir() for name in TEST_DIR_NAMES):
        return True
    # Python convention: test_*.py scattered next to source, no tests/ dir.
    return any(path.glob("test_*.py")) or any(path.glob("*/test_*.py"))


def _has_ci(path: Path) -> bool:
    ci_dir = path / ".github" / "workflows"
    if not ci_dir.is_dir():
        return False
    return any(ci_dir.glob("*.yml")) or any(ci_dir.glob("*.yaml"))


def _git_last_commit_at(path: Path) -> datetime | None:
    if not (path / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "log", "-1", "--format=%cI"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return datetime.fromisoformat(result.stdout.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _has_recent_commit(path: Path, days: int = RECENT_COMMIT_DAYS) -> bool:
    last = _git_last_commit_at(path)
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last) <= timedelta(days=days)


@dataclass
class ProjectScore:
    name: str
    path: str
    language: str
    score: int
    signals: dict[str, bool] = field(default_factory=dict)


def score_project(path: Path) -> ProjectScore:
    signals = {
        "aakManifest": _has_aak_manifest(path),
        "structuredDocs": _has_structured_docs(path),
        "tests": _has_tests(path),
        "ci": _has_ci(path),
        "recentCommit": _has_recent_commit(path),
    }
    score = sum(SCORE_WEIGHT for present in signals.values() if present)
    return ProjectScore(
        name=path.name,
        path=str(path),
        language=_detect_language(path),
        score=score,
        signals=signals,
    )


def scan_portfolio(root: Path) -> list[ProjectScore]:
    if not root.is_dir():
        return []
    return [
        score_project(entry)
        for entry in sorted(root.iterdir())
        if entry.is_dir() and not entry.name.startswith(".")
    ]
