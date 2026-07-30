"""architecture-map MCP server -- exposes read-only architecture-map queries
to agents (Claude Code, Codex) so they can check for existing components
before writing new code.

One process serves one repo (`--repo-root`), matching the master plan's
pre-VPS deployment mode ("run as an on-demand local stdio process... stop
when the CLI task ends", section 7.2). Multi-repo namespacing behind a
shared authenticated service is a post-VPS concern (section 7.2, "after the
new VPS, when remote acceleration is enabled") and is intentionally not
implemented here.

Known gap: `find_similar` and `get_impact_graph` (section 7.1) are not
implemented. Both need import/dependency-edge extraction that the scanner
(`aak.scan.core`) does not currently produce -- adding them requires scanner
work first, not just a new MCP tool.
"""
from __future__ import annotations
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .manifest import load_manifest, ManifestError, ProjectManifest

mcp = FastMCP("architecture-map")

_manifest: ProjectManifest | None = None
_repo_root: Path | None = None
SUPPORTED_INDEX_SCHEMA_VERSIONS = {"1.0"}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _get_manifest() -> ProjectManifest:
    global _manifest
    if _manifest is None:
        _manifest = load_manifest(_repo_root)
    return _manifest


def _read_map() -> dict:
    manifest = _get_manifest()
    with open(manifest.map_path, encoding="utf-8") as f:
        return json.load(f)


def _git_value(*args: str) -> str | None:
    if _repo_root is None:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(_repo_root), *args],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def _git_success(*args: str) -> bool:
    if _repo_root is None:
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(_repo_root), *args],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _commit_problem(commit: object, observed: str | None, label: str) -> str | None:
    """Validate an exact commit SHA and constrain it to the served checkout."""
    if not isinstance(commit, str) or not SHA_RE.fullmatch(commit):
        return f"{label} commit is absent or invalid; a full 40-character SHA is required"
    if not _git_success("cat-file", "-e", f"{commit}^{{commit}}"):
        return f"{label} commit does not exist in the served repository"
    if observed is None or not SHA_RE.fullmatch(observed):
        return "observed repository commit could not be verified"
    if not _git_success("merge-base", "--is-ancestor", commit, observed):
        return f"{label} commit is outside the served branch history"
    return None


def _index_status(expected_commit: str | None = None) -> dict:
    """Compute a fail-closed freshness contract without exposing repo content."""
    manifest = _get_manifest()
    observed = _git_value("rev-parse", "HEAD")
    expected = expected_commit
    branch = _git_value("branch", "--show-current") or "detached"
    base = {
        "repository": manifest.repo_id,
        "branch": branch,
        "expectedCommit": expected,
        "observedCommit": observed,
        "indexedCommit": None,
        "sourceSha": None,
        "indexedAt": None,
        "schemaVersion": None,
        "indexedFileCount": None,
        "componentCount": None,
        "includedScope": list(manifest.source_roots),
        "excludedScope": [".git", "node_modules", ".next", "coverage", "dist", "build", "__pycache__", ".venv", "venv"],
        "freshness": "unknown",
        "reason": "index metadata could not be verified",
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    marker = manifest.map_path.with_suffix(manifest.map_path.suffix + ".indexing")
    if marker.exists():
        try:
            marker_data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {**base, "freshness": "failed", "reason": "indexing marker is invalid"}
        if not isinstance(marker_data, dict) or marker_data.get("status") not in {
            "requested", "indexing", "validating", "ready", "publishing",
        }:
            return {**base, "freshness": "failed", "reason": "indexing marker is invalid"}
        return {**base, "freshness": "indexing", "reason": "an isolated index build is in progress"}
    try:
        data = _read_map()
    except (OSError, json.JSONDecodeError) as exc:
        return {**base, "freshness": "failed", "reason": f"index backend unavailable or invalid: {type(exc).__name__}"}
    source_sha = data.get("sourceSha")
    schema = data.get("schemaVersion")
    components = data.get("components")
    status = {
        **base,
        "indexedCommit": source_sha,
        "sourceSha": source_sha,
        "indexedAt": data.get("generatedAt"),
        "schemaVersion": schema,
        "indexedFileCount": len(components) if isinstance(components, list) else None,
        "componentCount": len(components) if isinstance(components, list) else None,
        "includedScope": data.get("sourceRoots", base["includedScope"]),
        "coverage": data.get("coverage"),
        "extractionMethod": data.get("extractionMethod"),
    }
    if schema not in SUPPORTED_INDEX_SCHEMA_VERSIONS:
        return {**status, "freshness": "incompatible", "reason": f"unsupported index schema version: {schema!r}"}
    if data.get("repoId") != manifest.repo_id:
        return {**status, "freshness": "incompatible", "reason": "index repository does not match the configured project"}
    if not isinstance(components, list):
        return {**status, "freshness": "incompatible", "reason": "index components field is not an array"}
    source_problem = _commit_problem(source_sha, observed, "indexed")
    if source_problem:
        return {**status, "freshness": "unknown", "reason": source_problem}
    expected_problem = _commit_problem(expected, observed, "expected")
    if expected_problem:
        return {**status, "freshness": "unknown", "reason": expected_problem}
    if source_sha != expected:
        return {**status, "freshness": "stale", "reason": "indexed commit does not match the expected commit"}
    return {**status, "freshness": "fresh", "reason": "indexed commit matches the expected commit"}


def _freshness_error(expected_commit: str | None = None) -> dict | None:
    status = _index_status(expected_commit)
    if status["freshness"] == "fresh":
        return None
    failed = status["freshness"] == "failed"
    return {
        "error": {
            "code": "INDEX_BACKEND_UNAVAILABLE" if failed else "INDEX_NOT_FRESH",
            "message": (
                "architectural conclusion blocked because the index backend is unavailable"
                if failed else
                "architectural conclusion blocked because the index is not fresh"
            ),
            "retryable": status["freshness"] in {"indexing", "failed", "stale"},
        },
        "index": status,
        "historicalOnly": status["freshness"] == "stale",
    }


def _read_incidents() -> list:
    manifest = _get_manifest()
    if not manifest.incidents_path.is_file():
        return []
    with open(manifest.incidents_path, encoding="utf-8") as f:
        return json.load(f)


def _adr_dir() -> Path:
    manifest = _get_manifest()
    rel = manifest.architecture.get("adrs", "docs/adr")
    return manifest.repo_root / rel


def _check_repo_id(repoId: str) -> dict | None:
    """Validate the caller-supplied repoId against the repo this process
    actually serves. Returns an error dict if it doesn't match, else None.

    This process is single-repo (see module docstring); repoId is not used
    for routing. It exists so a caller can't silently get answers for the
    wrong repo if it mixed up which server instance it's talking to.
    """
    manifest = _get_manifest()
    if repoId != manifest.repo_id:
        return {"error": f"repoId mismatch: this server instance serves '{manifest.repo_id}', not '{repoId}'"}
    return None


def _search_components(query: str, limit: int) -> list[dict]:
    data = _read_map()
    q = query.lower()
    results = []
    for c in data.get("components", []):
        if q in c["path"].lower() or any(q in e.lower() for e in c.get("exports", [])):
            results.append(c)
            if len(results) >= limit:
                break
    return results


def _get_component(path: str) -> dict:
    data = _read_map()
    for c in data.get("components", []):
        if c["path"] == path:
            return c
    return {"error": f"component not found: {path}"}


@mcp.tool()
def search_capability(repoId: str, query: str, limit: int = 20, expectedCommit: str | None = None) -> list[dict]:
    """Search architecture-map components by substring in path or exports.

    Use BEFORE writing any new helper, route, or component to confirm
    something similar doesn't already exist. Case-insensitive.

    Args:
        repoId: repo identifier from the project manifest (e.g. "mhx/lexnotify")
        query: search term (e.g. "chat", "notification", "getOrCreate")
        limit: max results to return (default 20)

    Returns:
        List of {path, exports, layer} that match, or {"error": "..."} on repoId mismatch.
    """
    err = _check_repo_id(repoId)
    if err:
        return [err]
    freshness_err = _freshness_error(expectedCommit)
    if freshness_err:
        return [freshness_err]
    return _search_components(query, limit)


@mcp.tool()
def get_component(repoId: str, componentId: str, expectedCommit: str | None = None) -> dict:
    """Return the full architecture-map entry for a component by exact path.

    Args:
        repoId: repo identifier from the project manifest (e.g. "mhx/lexnotify")
        componentId: file path relative to repo root (e.g. "src/lib/case-chat.ts")

    Returns:
        {path, exports, layer}, or {"error": "..."} if not found or repoId mismatch.
    """
    err = _check_repo_id(repoId)
    if err:
        return err
    freshness_err = _freshness_error(expectedCommit)
    if freshness_err:
        return freshness_err
    return _get_component(componentId)


@mcp.tool()
def check_duplication(description: str, expectedCommit: str | None = None) -> dict:
    """Check whether a described capability likely already exists.

    Cross-references known duplication incidents (business terms / accepted
    aliases) plus a textual search over the architecture map. Use before
    implementing anything that sounds generic (chat, notifications, auth,
    etc.) to avoid recreating logic that lives elsewhere.

    Args:
        description: plain-language description of what's about to be built

    Returns:
        {matchedIncident: {...} | null, candidateComponents: [...]}.
        matchedIncident, when present, points at the canonical target
        (path + symbol) that should be reused instead of rebuilt.
    """
    freshness_err = _freshness_error(expectedCommit)
    if freshness_err:
        return freshness_err
    incidents = _read_incidents()
    desc_lower = description.lower()

    matched = None
    for incident in incidents:
        terms = incident.get("businessTerms", []) + incident.get("acceptedAliases", [])
        if any(term.lower() in desc_lower for term in terms):
            matched = incident
            break

    data = _read_map()
    words = [w for w in desc_lower.split() if len(w) > 3]
    candidates = []
    if words:
        for c in data.get("components", []):
            haystack = (c["path"] + " " + " ".join(c.get("exports", []))).lower()
            if any(w in haystack for w in words):
                candidates.append(c)
                if len(candidates) >= 10:
                    break

    return {"matchedIncident": matched, "candidateComponents": candidates}


@mcp.tool()
def list_adrs(expectedCommit: str | None = None) -> list[dict]:
    """List the repo's Architecture Decision Records.

    Returns:
        List of {slug, title, path}.
    """
    freshness_err = _freshness_error(expectedCommit)
    if freshness_err:
        return [freshness_err]
    adr_dir = _adr_dir()
    if not adr_dir.is_dir():
        return []
    manifest = _get_manifest()
    out = []
    for f in sorted(adr_dir.glob("*.md")):
        title = f.stem
        try:
            first_line = f.read_text(encoding="utf-8").splitlines()[0]
            title = first_line.lstrip("#").strip() or title
        except OSError:
            pass
        out.append({
            "slug": f.stem,
            "title": title,
            "path": str(f.relative_to(manifest.repo_root)),
        })
    return out


@mcp.tool()
def get_adr(slug: str, expectedCommit: str | None = None) -> str | dict:
    """Return the full markdown content of an ADR by slug.

    Args:
        slug: filename without extension (see list_adrs)

    Returns:
        Markdown content, or an "error: ..." string if not found.
    """
    freshness_err = _freshness_error(expectedCommit)
    if freshness_err:
        return freshness_err
    path = _adr_dir() / f"{slug}.md"
    if not path.is_file():
        return f"error: ADR not found: {slug}"
    return path.read_text(encoding="utf-8")


@mcp.tool()
def get_map_status(repoId: str, expectedCommit: str | None = None) -> dict:
    """Return architecture-map metadata: when it was generated, from which
    commit, coverage, and component count. Use to judge whether the map
    might be stale before trusting an answer from the other tools.

    Args:
        repoId: repo identifier from the project manifest (e.g. "mhx/lexnotify")

    Returns:
        {generatedAt, sourceSha, coverage, componentCount, extractionMethod},
        or {"error": "..."} on repoId mismatch.
    """
    err = _check_repo_id(repoId)
    if err:
        return err
    return _index_status(expectedCommit)


@mcp.tool()
def verify_references(repoId: str, paths: list[str], symbols: list[str], expectedCommit: str | None = None) -> dict:
    """Cross-check cited file paths and exported symbols against the current
    architecture map. Use to validate evidence before citing it in a Codex
    audit or Gemini brief -- "not found" without recorded search coverage is
    not valid evidence (master plan section 3.5).

    Args:
        repoId: repo identifier from the project manifest (e.g. "mhx/lexnotify")
        paths: file paths to verify (relative to repo root)
        symbols: exported symbol names to verify (searched across all components)

    Returns:
        {missingPaths: [...], missingSymbols: [...], verifiedPaths: [...], verifiedSymbols: [...]}
        or {"error": "..."} on repoId mismatch.
    """
    err = _check_repo_id(repoId)
    if err:
        return err
    freshness_err = _freshness_error(expectedCommit)
    if freshness_err:
        return freshness_err

    data = _read_map()
    components = data.get("components", [])
    known_paths = {c["path"] for c in components}
    known_symbols = {e for c in components for e in c.get("exports", [])}

    verified_paths = [p for p in paths if p in known_paths]
    missing_paths = [p for p in paths if p not in known_paths]
    verified_symbols = [s for s in symbols if s in known_symbols]
    missing_symbols = [s for s in symbols if s not in known_symbols]

    return {
        "verifiedPaths": verified_paths,
        "missingPaths": missing_paths,
        "verifiedSymbols": verified_symbols,
        "missingSymbols": missing_symbols,
    }


def serve(repo_root: Path) -> None:
    """Entry point called by `aak mcp serve --repo-root <path>`."""
    global _repo_root
    _repo_root = Path(repo_root).resolve()
    load_manifest(_repo_root)  # fail fast if the manifest is missing/broken
    mcp.run()
