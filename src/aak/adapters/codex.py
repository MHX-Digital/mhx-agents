"""Codex CLI PreToolUse payload normalization.

Empirically confirmed shapes (2026-07-27, Codex CLI v0.145.0):
  apply_patch: {"tool_name": "apply_patch", "tool_input": {"command": "*** Begin Patch\\n*** Add File: <path>\\n...*** End Patch\\n"}}
  Bash:        {"tool_name": "Bash", "tool_input": {"command": ...}}

Note: PreToolUse hooks only fire once trusted via the interactive TUI ("Hooks
need review" prompt); the trust hash is then persisted in config.toml under
[hooks.state] and also applies to headless `codex exec` runs. See
FINDINGS.md at the kit root for the full writeup.
"""
import re

from . import NormalizedCall

PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)

WRITE_TOOLS = {"apply_patch", "Edit", "Write"}
SHELL_TOOLS = {"Bash"}


def _extract_patch_path(patch_text: str) -> str | None:
    match = PATCH_FILE_RE.search(patch_text or "")
    return match.group(1).strip() if match else None


def normalize(payload: dict) -> NormalizedCall:
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}

    if tool_name == "apply_patch":
        patch_text = tool_input.get("command", "")
        return NormalizedCall(
            kind="write",
            target_path=_extract_patch_path(patch_text),
            content=patch_text,
            command=None,
            raw_tool_name=tool_name,
        )
    if tool_name in WRITE_TOOLS:
        return NormalizedCall(
            kind="write",
            target_path=tool_input.get("file_path"),
            content=tool_input.get("content"),
            command=None,
            raw_tool_name=tool_name,
        )
    if tool_name in SHELL_TOOLS:
        return NormalizedCall(
            kind="shell",
            target_path=None,
            content=None,
            command=tool_input.get("command"),
            raw_tool_name=tool_name,
        )
    return NormalizedCall(kind="other", target_path=None, content=None, command=None, raw_tool_name=tool_name)
