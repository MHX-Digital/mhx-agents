"""Path resolution for the Agent Architecture Kit.

State root defaults to /srv/agent-architecture/state (Linux/VPS target from the
master plan). Overridable via AAK_STATE_ROOT for local/dev use.
"""
import os
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[2]


def state_root() -> Path:
    override = os.environ.get("AAK_STATE_ROOT")
    if override:
        return Path(override)
    return Path("/srv/agent-architecture/state")


def decisions_dir() -> Path:
    return state_root() / "decisions"


def locks_dir() -> Path:
    return state_root() / "locks"


def audit_dir() -> Path:
    return state_root() / "audit"


def overrides_dir() -> Path:
    return state_root() / "overrides"


def cache_dir() -> Path:
    return state_root() / "cache"


def find_repo_root(start: Path) -> Path | None:
    """Walk up from `start` looking for .agent-architecture/project.yaml."""
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".agent-architecture" / "project.yaml").is_file():
            return candidate
    return None
