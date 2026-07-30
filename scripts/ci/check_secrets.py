#!/usr/bin/env python3
"""High-confidence tracked-file secret scan with aggregate-only output."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
)
MAX_BYTES = 2_000_000


def main() -> int:
    paths = subprocess.run(
        ["git", "ls-files", "-z"], check=True, capture_output=True,
    ).stdout.split(b"\0")
    matches = unreadable = oversized = 0
    for raw in paths:
        if not raw:
            continue
        path = Path(raw.decode("utf-8", "surrogateescape"))
        try:
            if path.stat().st_size > MAX_BYTES:
                oversized += 1
                continue
            payload = path.read_bytes()
        except OSError:
            unreadable += 1
            continue
        matches += int(any(pattern.search(payload) for pattern in PATTERNS))
    print(
        f"secret_scan files={len(paths) - 1} matches={matches} "
        f"oversized={oversized} unreadable={unreadable}"
    )
    return 1 if matches or unreadable else 0


if __name__ == "__main__":
    raise SystemExit(main())
