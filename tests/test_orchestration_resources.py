import json
import subprocess
from unittest.mock import patch

from aak import orchestrate


def test_external_planner_schema_exists_during_invocation(tmp_path):
    def planner(args, **kwargs):
        from pathlib import Path
        schema = Path(args[args.index("--output-schema") + 1])
        assert json.loads(schema.read_text())["type"] == "object"
        target = Path(args[args.index("--output-last-message") + 1])
        target.write_text(json.dumps({"verdict": "DUPLICADO", "summary": "fictional",
                                     "reasoning": "fixture", "allowedExistingPaths": [], "allowedNewPaths": []}))
        return subprocess.CompletedProcess(args, 0, "", "")
    with patch("aak.orchestrate.subprocess.run", side_effect=planner):
        assert orchestrate._run_codex_plan(tmp_path, "fictional request")["verdict"] == "DUPLICADO"


def test_executor_preserves_default_client_permissions(tmp_path):
    plan = {"verdict": "NOVO", "summary": "fictional", "reasoning": "fixture",
            "allowedExistingPaths": [], "allowedNewPaths": ["src/example.py"]}
    with patch("aak.orchestrate.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "fixture", "")) as run:
        assert orchestrate._run_claude_execute(tmp_path, "fictional request", plan) == "fixture"
        assert "--dangerously-skip-permissions" not in run.call_args.args[0]
