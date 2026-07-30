#!/usr/bin/env python3
"""Sanitized local benchmark for MCP query and publication paths."""
from __future__ import annotations

import argparse
import json
import resource
import statistics
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from aak import mcp_server
from aak.index_lifecycle import IndexLifecycle
from aak.manifest import ProjectManifest
from aak.security import SecurityBoundary, issue_token

KEY = b"benchmark-key-is-synthetic-and-not-a-credential"
NOW = 1_800_000_000


def percentile(values, p):
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * p))))
    return ordered[index]


def timed(call):
    started = time.perf_counter_ns()
    value = call()
    return (time.perf_counter_ns() - started) / 1_000_000, value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=5000)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--components", type=int, default=848)
    args = parser.parse_args()
    if args.iterations < 100 or not 1 <= args.concurrency <= 256 or not 1 <= args.components <= 100_000:
        raise SystemExit("invalid benchmark bounds")

    with tempfile.TemporaryDirectory(prefix="aak-benchmark-") as temporary:
        root = Path(temporary)
        subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "bench@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Benchmark"], check=True)
        (root / "tracked.txt").write_text("synthetic")
        subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "fixture"], check=True, capture_output=True)
        sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                             capture_output=True, text=True).stdout.strip()
        manifest = ProjectManifest(
            schema_version="1.0", repo_id="benchmark/repo", tier=1,
            default_branch="main", kit_version="benchmark", source_roots=["src"],
            architecture={"map": "docs/architecture/ARCHITECTURE_MAP.json"}, repo_root=root,
        )
        components = [{"path": f"src/component-{i}.ts", "exports": [f"Symbol{i}"], "layer": "lib"}
                      for i in range(args.components)]
        doc = {"schemaVersion": "1.0", "repoId": "benchmark/repo", "sourceSha": sha,
               "generatedAt": datetime.now(timezone.utc).isoformat(), "components": components}
        manifest.map_path.parent.mkdir(parents=True)
        manifest.map_path.write_text(json.dumps(doc))
        boundary = SecurityBoundary({"benchmark": KEY}, clock=lambda: NOW,
                                    rate_limit=args.iterations * 4, response_limit=2_000_000)
        mcp_server._repo_root = root
        mcp_server._manifest = manifest
        mcp_server._security = boundary
        token = issue_token("benchmark", KEY, {
            "sub": "benchmark", "project": "benchmark/repo", "tenant": "sanitized",
            "role": "reader", "tools": ["get_map_status", "search_capability"],
            "exp": NOW + 3600, "jti": "benchmark-run",
        })

        def status_call():
            return mcp_server.get_map_status("benchmark/repo", sha, tenantId="sanitized", authToken=token)

        def search_call(index):
            return mcp_server.search_capability(
                "benchmark/repo", f"Symbol{index % args.components}", 20, sha,
                tenantId="sanitized", authToken=token,
            )

        warmup = [status_call() for _ in range(100)]
        assert all(item.get("freshness") == "fresh" for item in warmup)
        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            observations = list(pool.map(lambda i: timed(lambda: search_call(i)), range(args.iterations)))
        wall = time.perf_counter() - wall_start
        cpu = time.process_time() - cpu_start
        latencies = [item[0] for item in observations]
        errors = sum(1 for _, result in observations if isinstance(result, dict) and "error" in result)
        errors += sum(1 for _, result in observations if isinstance(result, list) and result and "error" in result[0])

        lifecycle = IndexLifecycle(root, manifest)
        publication_ms, publication = timed(lambda: lifecycle.publish(
            "main", sha,
            lambda path, resolved, workspace: path.write_text(json.dumps(doc)),
            operator="sanitized-benchmark", origin="local-benchmark", indexer_version="benchmark",
        ))
        rollback_ms, rollback = timed(lambda: lifecycle.rollback(publication.previous_index, operator="sanitized-benchmark"))
        state_bytes = sum(path.stat().st_size for path in lifecycle.state_root.rglob("*") if path.is_file())
        output = {
            "toolVersion": "1.0", "timestamp": datetime.now(timezone.utc).isoformat(),
            "environment": "local-sanitized", "python": __import__("platform").python_version(),
            "iterations": args.iterations, "concurrency": args.concurrency,
            "componentCount": args.components, "indexBytes": manifest.map_path.stat().st_size,
            "query": {
                "p50Ms": round(percentile(latencies, 0.50), 4),
                "p95Ms": round(percentile(latencies, 0.95), 4),
                "p99Ms": round(percentile(latencies, 0.99), 4),
                "maxMs": round(max(latencies), 4), "wallSeconds": round(wall, 4),
                "throughputPerSecond": round(args.iterations / wall, 2),
                "errorCount": errors, "errorRate": round(errors / args.iterations, 6),
            },
            "publication": {"publishMs": round(publication_ms, 4), "rollbackMs": round(rollback_ms, 4),
                            "status": publication.status, "rollbackStatus": rollback.status},
            "resources": {"cpuSeconds": round(cpu, 4), "maxRssKiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                          "stateBytes": state_bytes},
            "limitations": ["synthetic metadata only", "single host", "warm filesystem cache",
                            "no network transport", "max RSS is process high-water mark"],
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
