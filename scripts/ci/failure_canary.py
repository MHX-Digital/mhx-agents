#!/usr/bin/env python3
"""Maintainer-only dispatch: deliberately fail using disposable fictional files.

Nothing created here is staged in, or committed to, the product repository.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    gate = Path(__file__).with_name("check_whitespace.py")
    with tempfile.TemporaryDirectory(prefix="aak-deliberate-failure-") as directory:
        root = Path(directory)
        for args in [["init", "-b", "main"], ["config", "user.name", "Fictional canary"],
                     ["config", "user.email", "fixture@example.invalid"]]:
            subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
        (root / "example.txt").write_text("deliberate trailing whitespace  \n")
        for args in [["add", "."], ["commit", "-m", "Disposable canary"]]:
            subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
        whitespace = subprocess.run([sys.executable, str(gate), "--repo-root", str(root), "--base", ""],
                                    capture_output=True, timeout=15).returncode
        (root / "test_deliberate_failure.py").write_text("def test_deliberate_failure():\n    assert False, 'fictional canary'\n")
        pytest = subprocess.run([sys.executable, "-m", "pytest", "-q", str(root / "test_deliberate_failure.py")],
                               cwd=root, capture_output=True, timeout=20).returncode
    print(json.dumps({"synthetic_only": True, "product_files_changed": False,
                      "whitespace_exit": whitespace, "pytest_exit": pytest,
                      "temporary_resources_removed": True, "intentional_job_failure": True}))
    return 1 if whitespace != 0 and pytest == 1 else 2


if __name__ == "__main__":
    raise SystemExit(main())
