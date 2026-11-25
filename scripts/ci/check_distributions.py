#!/usr/bin/env python3
"""Build both artifacts and exercise installed CLIs in clean offline venvs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile


def run(args, cwd, env, expected=0):
    result = subprocess.run([str(a) for a in args], cwd=cwd, env=env,
                            capture_output=True, text=True, timeout=120)
    if result.returncode != expected:
        raise RuntimeError(f"distribution check failed: {Path(str(args[0])).name}: {result.stderr[-1500:]}")
    return result.stdout


def check(wheelhouse):
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update(PIP_NO_INDEX="1", PIP_FIND_LINKS=str(wheelhouse.resolve()),
               PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONDONTWRITEBYTECODE="1")
    sha = run(["git", "rev-parse", "HEAD"], root, env).strip()
    clean = subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=root).returncode == 0
    result = {"source_commit": sha, "tracked_tree_clean": clean, "artifacts": [],
              "synthetic_only": True, "default_state_written": False}
    with tempfile.TemporaryDirectory(prefix="aak-package-check-") as directory:
        work = Path(directory)
        source = work / "source"
        source.mkdir()
        for raw in subprocess.check_output(["git", "ls-files", "-z"], cwd=root).split(b"\0"):
            if not raw:
                continue
            rel = Path(os.fsdecode(raw))
            original = root / rel
            if original.is_symlink() or not original.resolve().is_relative_to(root.resolve()):
                raise RuntimeError("unexpected source symlink")
            target = source / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
        dist = work / "dist"
        run([sys.executable, "-m", "build", "--sdist", "--wheel", "--no-isolation", "--outdir", dist], source, env)
        artifacts = [next(dist.glob("*.whl")), next(dist.glob("*.tar.gz"))]
        schemas = {p.name for p in (root / "schemas").glob("*.json")}
        assert len(schemas) == 7
        for index, artifact in enumerate(artifacts):
            if artifact.suffix == ".whl":
                with zipfile.ZipFile(artifact) as z:
                    names = z.namelist()
            else:
                with tarfile.open(artifact) as tar:
                    names = tar.getnames()
            assert all(any(("/" + n).endswith("/aak/schemas/" + s) for n in names) for s in schemas)
            venv = work / f"venv-{index}"
            run([sys.executable, "-m", "venv", venv], work, env)
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            run([python, "-m", "pip", "install", "--no-index", "--find-links", wheelhouse, artifact], work, env)
            run([python, "-m", "pip", "check"], work, env)
            demo = work / f"example-{index}"
            (demo / ".agent-architecture").mkdir(parents=True)
            (demo / "src").mkdir()
            (demo / "src/greetings.py").write_text('def greet(name):\n    return f"Hello, {name}!"\n')
            (demo / ".agent-architecture/project.yaml").write_text(
                'schemaVersion: "1.0"\nrepoId: "example/greetings"\ntier: 1\ndefaultBranch: main\n'
                'kitVersion: "1.0.0"\nsourceRoots: [src]\narchitecture:\n  map: docs/architecture/ARCHITECTURE_MAP.json\n')
            run(["git", "init", "-b", "main"], demo, env)
            run(["git", "add", "."], demo, env)
            run(["git", "-c", "user.name=Fictional example", "-c", "user.email=fixture@example.invalid",
                 "commit", "-m", "Synthetic package fixture"], demo, env)
            version = run([python, "-I", "-m", "aak", "--version"], work, env).strip()
            run([python, "-I", "-m", "aak", "scan", "run", "--repo-root", demo, "--language", "python"], work, env)
            run([python, "-I", "-m", "aak", "verify", "--repo-root", demo, "--language", "python"], work, env)
            doc = json.loads((demo / "docs/architecture/ARCHITECTURE_MAP.json").read_text())
            assert doc["components"][0]["exports"] == ["greet"]
            probe = ('import json, aak; from aak.schema_resources import SCHEMA_NAMES, load_schema; '
                     'from aak.paths import KIT_ROOT; '
                     'assert all(load_schema(n)["type"]=="object" for n in SCHEMA_NAMES); '
                     'print(json.dumps({"schemas":len(SCHEMA_NAMES),"package_root":KIT_ROOT.name}))')
            identity = json.loads(run([python, "-I", "-c", probe], work, env))
            assert identity == {"schemas": 7, "package_root": "aak"}
            bad = demo / ".agent-architecture/project.yaml"
            bad.write_text(bad.read_text() + "unknownFixtureField: true\n")
            rejected = subprocess.run([str(python), "-I", "-m", "aak", "verify", "--repo-root", str(demo)],
                                      cwd=work, env=env, capture_output=True, text=True, timeout=15)
            assert rejected.returncode != 0 and "manifest invalid" in rejected.stdout
            result["artifacts"].append({"name": artifact.name, "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                                        "schemas": 7, "version": version, "scan_and_verify": "pass",
                                        "invalid_manifest": "denied", "isolated_import": True,
                                        "clean_venv": True, "cwd_outside_checkout": True})
    result["temporary_resources_removed"] = True
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = check(args.wheelhouse)
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    print(text)
