"""Fixture-based validation for every schema in schemas/. Fixtures mirror
what the producing code actually emits (aak.scan.core.build_doc,
aak.override.create_override, aak.decision, aak.manifest), not the
theoretical shapes from the master plan design doc.
"""
import json

import pytest
from jsonschema import Draft7Validator, validate, ValidationError

from aak.paths import KIT_ROOT

SCHEMAS_DIR = KIT_ROOT / "schemas"


def _load_schema(name: str) -> dict:
    with open(SCHEMAS_DIR / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("name", [
    "project.schema.json",
    "agent-evidence.schema.json",
    "task-decision.schema.json",
    "architecture-map.schema.json",
    "override.schema.json",
    "orchestrate-plan.schema.json",
    "codex-review.schema.json",
])
def test_schema_file_is_valid_json_schema(name):
    schema = _load_schema(name)
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert schema["$id"] == name
    Draft7Validator.check_schema(schema)


def test_architecture_map_accepts_real_scan_output():
    schema = _load_schema("architecture-map.schema.json")
    doc = {
        "schemaVersion": "1.0",
        "repoId": "mhx/lexnotify",
        "generatedAt": "2026-07-28T12:00:00+00:00",
        "sourceSha": "abc123",
        "extractionMethod": "typescript-regex-v1",
        "coverage": "app/, src/ (TypeScript/Next.js only)",
        "components": [
            {"path": "src/domain/cases/case-chat.ts", "exports": ["getOrCreateCaseChat"], "layer": "domain"},
            {"path": "src/lib/reexport.ts", "exports": [], "layer": "lib", "reExportsFrom": ["./other"]},
        ],
    }
    validate(instance=doc, schema=schema)


def test_architecture_map_rejects_component_missing_layer():
    schema = _load_schema("architecture-map.schema.json")
    doc = {
        "schemaVersion": "1.0",
        "repoId": "mhx/lexnotify",
        "generatedAt": "2026-07-28T12:00:00+00:00",
        "sourceSha": "abc123",
        "extractionMethod": "typescript-regex-v1",
        "coverage": "app/, src/",
        "components": [{"path": "src/x.ts", "exports": []}],
    }
    with pytest.raises(ValidationError):
        validate(instance=doc, schema=schema)


def test_architecture_map_rejects_missing_required_field():
    schema = _load_schema("architecture-map.schema.json")
    doc = {
        "schemaVersion": "1.0",
        "repoId": "mhx/lexnotify",
        "generatedAt": "2026-07-28T12:00:00+00:00",
        "sourceSha": "abc123",
        "coverage": "app/, src/",
        "components": [],
    }
    with pytest.raises(ValidationError):
        validate(instance=doc, schema=schema)


def test_override_accepts_real_create_override_output():
    schema = _load_schema("override.schema.json")
    override = {
        "schemaVersion": "1.0",
        "repoId": "mhx/lexnotify",
        "issue": 734,
        "scope": "src/chat/**",
        "reason": "Approved replacement after ADR-0042",
        "createdAt": "2026-07-28T12:00:00+00:00",
        "expiresAt": "2026-07-29T23:59:00-04:00",
        "authorizationHash": "sha256:" + "a" * 64,
    }
    validate(instance=override, schema=schema)


def test_override_rejects_malformed_authorization_hash():
    schema = _load_schema("override.schema.json")
    override = {
        "schemaVersion": "1.0",
        "repoId": "mhx/lexnotify",
        "issue": 734,
        "scope": "src/chat/**",
        "reason": "Approved replacement after ADR-0042",
        "createdAt": "2026-07-28T12:00:00+00:00",
        "expiresAt": "2026-07-29T23:59:00-04:00",
        "authorizationHash": "not-a-hash",
    }
    with pytest.raises(ValidationError):
        validate(instance=override, schema=schema)


def test_override_rejects_missing_issue():
    schema = _load_schema("override.schema.json")
    override = {
        "schemaVersion": "1.0",
        "repoId": "mhx/lexnotify",
        "scope": "src/chat/**",
        "reason": "Approved replacement after ADR-0042",
        "createdAt": "2026-07-28T12:00:00+00:00",
        "expiresAt": "2026-07-29T23:59:00-04:00",
        "authorizationHash": "sha256:" + "a" * 64,
    }
    with pytest.raises(ValidationError):
        validate(instance=override, schema=schema)


def test_override_rejects_non_positive_issue():
    schema = _load_schema("override.schema.json")
    override = {
        "schemaVersion": "1.0",
        "repoId": "mhx/lexnotify",
        "issue": 0,
        "scope": "src/chat/**",
        "reason": "Approved replacement after ADR-0042",
        "createdAt": "2026-07-28T12:00:00+00:00",
        "expiresAt": "2026-07-29T23:59:00-04:00",
        "authorizationHash": "sha256:" + "a" * 64,
    }
    with pytest.raises(ValidationError):
        validate(instance=override, schema=schema)


def test_project_manifest_rejects_unknown_tier():
    schema = _load_schema("project.schema.json")
    manifest = {
        "schemaVersion": "1.0",
        "repoId": "mhx/lexnotify",
        "tier": 7,
        "defaultBranch": "main",
        "kitVersion": "1.0.0",
    }
    with pytest.raises(ValidationError):
        validate(instance=manifest, schema=schema)


def test_task_decision_accepts_minimal_valid_decision():
    schema = _load_schema("task-decision.schema.json")
    decision = {
        "schemaVersion": "1.0",
        "kitVersion": "1.0.0",
        "repoId": "mhx/lexnotify",
        "tier": 1,
        "branch": "issue-734/unify-case-chat",
        "executor": "claude",
        "baseSha": "abc123",
        "createdAt": "2026-07-28T12:00:00+00:00",
        "expiresAt": "2026-07-29T12:00:00+00:00",
        "verdict": "ESTENDER_CONFIRMADO",
        "allowedExistingPaths": ["src/domain/cases/case-chat.ts"],
        "allowedNewPaths": [],
        "protectedDomains": ["chat"],
    }
    validate(instance=decision, schema=schema)
