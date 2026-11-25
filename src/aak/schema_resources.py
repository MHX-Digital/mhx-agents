"""Canonical runtime schemas, available in source, wheel and sdist installs."""
from contextlib import contextmanager
from importlib import resources
import json

SCHEMA_NAMES = frozenset({
    "project.schema.json", "agent-evidence.schema.json", "task-decision.schema.json",
    "architecture-map.schema.json", "override.schema.json", "orchestrate-plan.schema.json",
    "codex-review.schema.json",
})


def _resource(name):
    if name not in SCHEMA_NAMES:
        raise ValueError("unknown package schema")
    return resources.files("aak.schemas").joinpath(name)


def load_schema(name):
    return json.loads(_resource(name).read_text(encoding="utf-8"))


@contextmanager
def schema_file(name):
    """Keep a physical schema available throughout an external CLI invocation."""
    with resources.as_file(_resource(name)) as path:
        yield path
