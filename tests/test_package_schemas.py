import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from aak.paths import KIT_ROOT
from aak.schema_resources import SCHEMA_NAMES, load_schema, schema_file


def test_all_seven_packaged_schemas_match_canonical_source():
    assert len(SCHEMA_NAMES) == 7
    for name in SCHEMA_NAMES:
        value = load_schema(name)
        Draft7Validator.check_schema(value)
        assert value == json.loads((KIT_ROOT / "schemas" / name).read_text())
        with schema_file(name) as path:
            assert path.is_file()
            assert json.loads(path.read_text()) == value


def test_resource_names_cannot_escape_the_package():
    for name in ("../project.schema.json", "/etc/passwd", "missing.json"):
        with pytest.raises(ValueError):
            load_schema(name)
