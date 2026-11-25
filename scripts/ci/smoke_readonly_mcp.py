#!/usr/bin/env python3
"""Real stdio canary with synthetic data; no agent, external provider or service."""
import argparse
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from aak.security import issue_token

TOOLS = {"get_map_status", "search_capability", "get_component", "check_duplication",
         "list_adrs", "get_adr", "verify_references"}
KEY = "synthetic-canary-key-not-a-production-credential"


def unpack(result):
    if result.isError:
        raise RuntimeError("MCP protocol call failed in synthetic canary")
    value = getattr(result, "structuredContent", None)
    if value is not None:
        return value["result"] if set(value) == {"result"} else value
    parts = [json.loads(block.text) for block in result.content if block.type == "text"]
    return parts[0] if len(parts) == 1 else parts


async def check():
    code_root = Path(__file__).resolve().parents[2]
    code_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=code_root, text=True).strip()
    clean = subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=code_root).returncode == 0
    receipt = {"source_commit": code_sha, "tracked_tree_clean": clean, "synthetic_only": True, "transport": "stdio",
               "provider_calls": 0, "public_ports": 0, "successful_tools": [], "denied_cases": []}
    with tempfile.TemporaryDirectory(prefix="aak-mcp-canary-") as directory:
        root = Path(directory)
        for folder in ["src", ".agent-architecture", "docs/adr", "docs/architecture"]:
            (root / folder).mkdir(parents=True)
        (root / "src/greetings.py").write_text("def greet(name):\n    return name\n")
        (root / ".agent-architecture/project.yaml").write_text(
            'schemaVersion: "1.0"\nrepoId: "example/canary"\ntier: 1\ndefaultBranch: main\n'
            'kitVersion: "1.0.0"\nsourceRoots: [src]\n')
        (root / "docs/adr/001-storage.md").write_text("# Fictional storage\nStatus: accepted\nUse a local fixture.\n")
        for args in [["init", "-b", "main"], ["add", "."],
                     ["-c", "user.name=Fictional canary", "-c", "user.email=fixture@example.invalid",
                      "commit", "-m", "Synthetic canary source"]]:
            subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
        sha = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        map_path = root / "docs/architecture/ARCHITECTURE_MAP.json"
        map_path.write_text(json.dumps({"schemaVersion": "1.0", "repoId": "example/canary", "sourceSha": sha,
                                        "generatedAt": "2026-01-01T00:00:00Z", "components": [
                                            {"path": "src/greetings.py", "exports": ["greet"], "layer": "src"}]}))
        env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "AAK_MCP_AUDIT_PATH", "AAK_MCP_REVOKED_JTIS"}}
        env.update(AAK_MCP_AUTH_KEYS=json.dumps({"canary": KEY}), PYTHONDONTWRITEBYTECODE="1")
        claims = {"sub": "synthetic-reader", "project": "example/canary", "tenant": "tenant-example",
                  "role": "reader", "tools": sorted(TOOLS), "exp": int(time.time()) + 120, "jti": "synthetic-only"}
        token = issue_token("canary", KEY.encode(), claims)
        auth = {"expectedCommit": sha, "tenantId": "tenant-example", "authToken": token}
        server = StdioServerParameters(command=sys.executable,
            args=["-I", "-m", "aak", "mcp", "serve", "--repo-root", str(root)], env=env)
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=10)) as session:
                await session.initialize()
                assert {t.name for t in (await session.list_tools()).tools} == TOOLS
                calls = {
                    "get_map_status": {"repoId": "example/canary"},
                    "search_capability": {"repoId": "example/canary", "query": "greet"},
                    "get_component": {"repoId": "example/canary", "componentId": "src/greetings.py"},
                    "check_duplication": {"description": "greet"},
                    "list_adrs": {}, "get_adr": {"slug": "001-storage"},
                    "verify_references": {"repoId": "example/canary", "paths": ["src/greetings.py"], "symbols": ["greet"]},
                }
                for name, arguments in calls.items():
                    value = unpack(await session.call_tool(name, {**auth, **arguments}))
                    if name == "get_map_status": assert value["freshness"] == "fresh" and value["sourceSha"] == sha
                    elif name == "search_capability": assert value[0]["path"] == "src/greetings.py"
                    elif name == "get_component": assert value["exports"] == ["greet"]
                    elif name == "list_adrs": assert value[0]["slug"] == "001-storage"
                    elif name == "get_adr": assert value["contentTrust"] == "untrusted_repository_data"
                    elif name == "verify_references": assert value["verifiedSymbols"] == ["greet"]
                    else: assert "candidateComponents" in value
                    receipt["successful_tools"].append(name)

                async def denied(label, tool, arguments, code):
                    value = unpack(await session.call_tool(tool, arguments))
                    if isinstance(value, list): value = value[0]
                    assert value["error"]["code"] == code, label
                    receipt["denied_cases"].append(label)
                status = {**auth, "repoId": "example/canary"}
                await denied("missing-auth", "get_map_status", {k:v for k,v in status.items() if k != "authToken"}, "AUTHENTICATION_REQUIRED")
                expired = issue_token("canary", KEY.encode(), {**claims, "exp": int(time.time()) - 1})
                await denied("expired-auth", "get_map_status", {**status, "authToken": expired}, "AUTHENTICATION_EXPIRED")
                await denied("tenant-isolation", "get_map_status", {**status, "tenantId": "tenant-other"}, "AUTHORIZATION_DENIED")
                other = issue_token("canary", KEY.encode(), {**claims, "project": "example/other"})
                await denied("project-isolation", "get_map_status", {**status, "authToken": other}, "AUTHORIZATION_DENIED")
                await denied("missing-source-version", "get_component", {**auth, **calls["get_component"], "expectedCommit": "0" * 40}, "INDEX_NOT_FRESH")
                await denied("path-traversal", "get_adr", {**auth, "slug": "../outside"}, "INPUT_INVALID")
                marker = map_path.with_suffix(".json.indexing")
                marker.write_text('{"status":"indexing"}')
                await denied("indexing-source", "get_component", {**auth, **calls["get_component"]}, "INDEX_NOT_FRESH")
                marker.unlink()
                map_path.unlink()
                await denied("missing-index", "get_component", {**auth, **calls["get_component"]}, "INDEX_BACKEND_UNAVAILABLE")
        receipt["fixture_source_sha"] = sha
    receipt["temporary_resources_removed"] = True
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = asyncio.run(asyncio.wait_for(check(), timeout=45))
    text = json.dumps(receipt, indent=2) + "\n"
    if args.output: args.output.write_text(text)
    print(text)
