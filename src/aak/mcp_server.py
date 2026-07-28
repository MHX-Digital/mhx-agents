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
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .manifest import load_manifest, ManifestError, ProjectManifest

mcp = FastMCP("architecture-map")

_manifest: ProjectManifest | None = None
_repo_root: Path | None = None


def _get_manifest() -> ProjectManifest:
    global _manifest
    if _manifest is None:
        _manifest = load_manifest(_repo_root)
    return _manifest


def _read_map() -> dict:
    manifest = _get_manifest()
    with open(manifest.map_path, encoding="utf-8") as f:
        return json.load(f)


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
def search_capability(repoId: str, query: str, limit: int = 20) -> list[dict]:
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
    return _search_components(query, limit)


@mcp.tool()
def find_component(query: str, limit: int = 20) -> list[dict]:
    """Deprecated alias for search_capability without repoId validation.
    Kept for backward compatibility; prefer search_capability.
    """
    return _search_components(query, limit)


@mcp.tool()
def get_component(repoId: str, componentId: str) -> dict:
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
    return _get_component(componentId)


@mcp.tool()
def component_detail(path: str) -> dict:
    """Deprecated alias for get_component without repoId validation.
    Kept for backward compatibility; prefer get_component.
    """
    return _get_component(path)


@mcp.tool()
def check_duplication(description: str) -> dict:
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
def list_adrs() -> list[dict]:
    """List the repo's Architecture Decision Records.

    Returns:
        List of {slug, title, path}.
    """
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
def get_adr(slug: str) -> str:
    """Return the full markdown content of an ADR by slug.

    Args:
        slug: filename without extension (see list_adrs)

    Returns:
        Markdown content, or an "error: ..." string if not found.
    """
    path = _adr_dir() / f"{slug}.md"
    if not path.is_file():
        return f"error: ADR not found: {slug}"
    return path.read_text(encoding="utf-8")


def _map_status() -> dict:
    data = _read_map()
    return {
        "generatedAt": data.get("generatedAt"),
        "sourceSha": data.get("sourceSha"),
        "coverage": data.get("coverage"),
        "componentCount": len(data.get("components", [])),
        "extractionMethod": data.get("extractionMethod"),
    }


@mcp.tool()
def get_map_status(repoId: str) -> dict:
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
    return _map_status()


@mcp.tool()
def map_status() -> dict:
    """Deprecated alias for get_map_status without repoId validation.
    Kept for backward compatibility; prefer get_map_status.
    """
    return _map_status()


@mcp.tool()
def verify_references(repoId: str, paths: list[str], symbols: list[str]) -> dict:
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
