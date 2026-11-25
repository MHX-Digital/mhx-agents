"""Unified verification gate (master plan section 3.2's `aak verify`).

Composes the same primitives the pretool guard and `aak scan run --check`
already use behind one entry point, so "CI ran the gate" and "I ran `aak
verify` locally" mean the same thing. This is what
`ci/github/architecture-gate.yml` calls.

Honesty notes (deliberate, not oversights):
- `--language` is optional because the project manifest doesn't declare which
  scanner adapter to use (see cli.py's scan_run comment: kept explicit until
  a second consumer needs auto-detect). Without it, the drift check is
  reported as skipped, not silently passed as if it ran.
- The map-schema check treats a not-yet-generated map as a soft pass (a
  brand-new repo's first commits shouldn't be blocked on architecture
  tooling it hasn't bootstrapped yet), not a silent success -- the detail
  string says so either way.
- There is no `architecture-duplication` check here. That needs a real
  project-specific DUPLICATION_INCIDENTS.json evaluation. Callers must not
  infer that it ran merely because schema and drift checks passed.
"""
from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from pathlib import Path

import jsonschema

from .guard import evaluate_precommit
from .manifest import ManifestError, ProjectManifest, load_manifest
from .schema_resources import load_schema


@dataclass
class VerifyCheck:
    name: str
    passed: bool
    detail: str


def _load_schema(filename: str) -> dict:
    return load_schema(filename)


def _check_map_schema(manifest: ProjectManifest) -> VerifyCheck:
    if not manifest.map_path.is_file():
        return VerifyCheck("architecture-schema:map", True, f"{manifest.map_path} not generated yet, skipping")
    import json
    try:
        with open(manifest.map_path, encoding="utf-8") as f:
            doc = json.load(f)
    except json.JSONDecodeError as e:
        return VerifyCheck("architecture-schema:map", False, f"{manifest.map_path} is not valid JSON: {e}")
    try:
        jsonschema.validate(instance=doc, schema=_load_schema("architecture-map.schema.json"))
    except jsonschema.ValidationError as e:
        return VerifyCheck("architecture-schema:map", False, f"{manifest.map_path} failed schema validation: {e.message}")
    return VerifyCheck("architecture-schema:map", True, f"{manifest.map_path} is schema-valid")


def _check_drift(repo_root: Path, manifest: ProjectManifest, language: str) -> VerifyCheck:
    from .scan.adapters import ADAPTERS
    from .scan.core import run_scan

    adapter_cls = ADAPTERS.get(language)
    if adapter_cls is None:
        return VerifyCheck("architecture-drift", False, f"unknown language '{language}' (choices: {', '.join(sorted(ADAPTERS))})")

    md_path = repo_root / "docs" / "ARCHITECTURE_MAP.md"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = run_scan(
            repo_root=repo_root,
            repo_id=manifest.repo_id,
            source_roots=manifest.source_roots,
            adapter=adapter_cls(),
            out_json=manifest.map_path,
            md_path=md_path,
            check_mode=True,
        )
    return VerifyCheck("architecture-drift", code == 0, buf.getvalue().strip())


def _check_scope(cwd: Path) -> VerifyCheck:
    result = evaluate_precommit(cwd)
    return VerifyCheck("scope-verification", result.allowed, result.reason)


def run_verify(repo_root: Path, language: str | None, staged: bool) -> tuple[list[VerifyCheck], int]:
    checks: list[VerifyCheck] = []

    try:
        manifest = load_manifest(repo_root)
    except ManifestError as e:
        checks.append(VerifyCheck("architecture-schema:manifest", False, f"manifest invalid: {e}"))
        return checks, 1
    checks.append(VerifyCheck("architecture-schema:manifest", True, "project.yaml is schema-valid"))

    checks.append(_check_map_schema(manifest))

    if language:
        checks.append(_check_drift(repo_root, manifest, language))
    else:
        checks.append(VerifyCheck("architecture-drift", True, "skipped: no --language given"))

    if staged:
        checks.append(_check_scope(repo_root))
    else:
        checks.append(VerifyCheck("scope-verification", True, "skipped: --staged not passed"))

    exit_code = 0 if all(c.passed for c in checks) else 1
    return checks, exit_code
