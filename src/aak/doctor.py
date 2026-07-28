"""`aak doctor`: reports real, checked capability status per client.

Static findings below were verified live on this VPS on 2026-07-27 (session
that built this kit) and are not re-derived on every run, since re-running
the full interactive verification is expensive. Dynamic checks (binary
present, auth file present, AppArmor profile loaded) run every time.
"""
import shutil
import subprocess
from pathlib import Path

HOME = Path.home()

STATIC_FINDINGS = {
    "claude": [
        ("AGENTS.md auto-import", True, "confirmed 2026-07-27: `claude -p` answered from AGENTS.md content unprompted"),
        ("PreToolUse exit-2 block", True, "confirmed 2026-07-27: hook stderr message reached the agent, write was blocked"),
    ],
    "codex": [
        ("PreToolUse exit-2 block", True, "confirmed 2026-07-27: requires trusting the hook once via interactive TUI "
         "('Hooks need review' prompt); trust hash persists in ~/.codex/config.toml [hooks.state] and then also "
         "applies to headless `codex exec`"),
        ("sandbox workspace-write", True, "confirmed 2026-07-27: bundled bwrap failed with 'setting up uid map: "
         "Permission denied' under Ubuntu 24.04's AppArmor unprivileged-userns restriction until a scoped profile "
         "was installed at /etc/apparmor.d/codex-bwrap"),
    ],
}

# Gemini CLI was removed from this kit's scope on 2026-07-28: the account's
# Google AI Pro/Ultra (Gemini Advanced) consumer subscription does not carry
# a Gemini Code Assist license, so "Sign in with Google" silently falls back
# to the API key method every time, and the AI Studio API key free tier caps
# at 20 requests/day - not usable for an executor role. Architecture-map
# duties were folded into Claude Code instead of a third model/account.


def _binary_status(name: str) -> str:
    return shutil.which(name) or "NOT FOUND on PATH"


def _auth_status(client: str) -> str:
    checks = {
        "claude": HOME / ".claude" / ".credentials.json",
        "codex": HOME / ".codex" / "auth.json",
    }
    p = checks.get(client)
    if p and p.is_file():
        return "credentials file present"
    return "NOT authenticated"


def _apparmor_codex_bwrap_status() -> str:
    try:
        result = subprocess.run(["sudo", "-n", "aa-status"], capture_output=True, text=True, timeout=10)
        if "codex-bwrap" in result.stdout:
            return "loaded"
        return "NOT loaded (codex sandbox writes will fail on Ubuntu 24.04+)"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "aa-status unavailable (non-AppArmor system, or not needed)"


def run() -> str:
    lines = ["aak doctor", "=" * 60]
    for client in ("claude", "codex"):
        lines.append(f"\n[{client}]")
        lines.append(f"  binary:  {_binary_status(client)}")
        lines.append(f"  auth:    {_auth_status(client)}")
        for label, status, note in STATIC_FINDINGS[client]:
            status_str = {True: "CONFIRMED", False: "DENIED", None: "UNVERIFIED"}[status]
            lines.append(f"  [{status_str}] {label}: {note}")

    lines.append("\n[sandbox]")
    lines.append(f"  codex-bwrap AppArmor profile: {_apparmor_codex_bwrap_status()}")
    return "\n".join(lines)
