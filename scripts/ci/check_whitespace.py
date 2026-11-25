#!/usr/bin/env python3
"""Check the final PR diff, manual parent diff, or initial commit. No shell input."""
import argparse
import os
from pathlib import Path
import re
import subprocess


def check(repo, base=""):
    if base:
        if not re.fullmatch(r"[0-9a-f]{40}", base):
            return 2
        args = ["diff", "--check", f"{base}...HEAD"]
    else:
        parent = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "HEAD^"],
                                capture_output=True, timeout=10)
        args = (["diff", "--check", "HEAD^", "HEAD"] if parent.returncode == 0
                else ["show", "--format=", "--check", "HEAD"])
    return subprocess.run(["git", "-C", str(repo), *args], timeout=10).returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--base", default=os.environ.get("BASE_SHA", ""))
    args = parser.parse_args()
    raise SystemExit(check(args.repo_root, args.base))
