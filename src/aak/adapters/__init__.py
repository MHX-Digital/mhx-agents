"""Client adapters: normalize each CLI's native PreToolUse hook payload.

Payload shapes below were captured empirically from live hook invocations on
2026-07-27 (Claude Code v2.1.220, Codex CLI v0.145.0), not assumed from docs.
"""
from dataclasses import dataclass


@dataclass
class NormalizedCall:
    kind: str  # "write" | "shell" | "other"
    target_path: str | None
    content: str | None
    command: str | None
    raw_tool_name: str


def normalize(client: str, payload: dict) -> NormalizedCall:
    if client == "claude":
        from .claude import normalize as f
    elif client == "codex":
        from .codex import normalize as f
    else:
        raise ValueError(f"unknown client: {client}")
    return f(payload)
