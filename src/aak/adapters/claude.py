"""Claude Code PreToolUse payload normalization.

Empirically confirmed shapes (2026-07-27, Claude Code v2.1.220):
  Write:  {"tool_name": "Write", "tool_input": {"file_path": ..., "content": ...}}
  Edit:   {"tool_name": "Edit",  "tool_input": {"file_path": ..., "old_string": ..., "new_string": ...}}
  Bash:   {"tool_name": "Bash",  "tool_input": {"command": ..., "description": ...}}
"""
from . import NormalizedCall

WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}
SHELL_TOOLS = {"Bash"}


def normalize(payload: dict) -> NormalizedCall:
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}

    if tool_name in WRITE_TOOLS:
        return NormalizedCall(
            kind="write",
            target_path=tool_input.get("file_path") or tool_input.get("notebook_path"),
            content=tool_input.get("content") or tool_input.get("new_string"),
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
