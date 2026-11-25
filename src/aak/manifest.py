"""Load and validate the per-repository project manifest (.agent-architecture/project.yaml)."""
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jsonschema import validate, ValidationError

from .schema_resources import load_schema


class ManifestError(Exception):
    pass


@dataclass
class ProjectManifest:
    schema_version: str
    repo_id: str
    tier: int
    default_branch: str
    kit_version: str
    source_roots: list = field(default_factory=list)
    protected_domains: list = field(default_factory=list)
    generated_paths: list = field(default_factory=list)
    validation: dict = field(default_factory=dict)
    architecture: dict = field(default_factory=dict)
    repo_root: Path = None

    @property
    def incidents_path(self) -> Path:
        rel = self.architecture.get("incidents", "docs/architecture/DUPLICATION_INCIDENTS.json")
        return self.repo_root / rel

    @property
    def map_path(self) -> Path:
        rel = self.architecture.get("map", "docs/architecture/ARCHITECTURE_MAP.json")
        return self.repo_root / rel


def _schema():
    return load_schema("project.schema.json")


def load_manifest(repo_root: Path) -> ProjectManifest:
    manifest_path = repo_root / ".agent-architecture" / "project.yaml"
    if not manifest_path.is_file():
        raise ManifestError(f"missing repository manifest: {manifest_path}")

    with open(manifest_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    try:
        validate(instance=raw, schema=_schema())
    except ValidationError as e:
        raise ManifestError(f"manifest schema validation failed: {e.message}") from e

    return ProjectManifest(
        schema_version=raw["schemaVersion"],
        repo_id=raw["repoId"],
        tier=raw["tier"],
        default_branch=raw["defaultBranch"],
        kit_version=raw["kitVersion"],
        source_roots=raw.get("sourceRoots", []),
        protected_domains=raw.get("protectedDomains", []),
        generated_paths=raw.get("generatedPaths", []),
        validation=raw.get("validation", {}),
        architecture=raw.get("architecture", {}),
        repo_root=repo_root,
    )
