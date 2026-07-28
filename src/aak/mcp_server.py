"""lexnotify-map MCP server -- exposes architecture-map queries to agents
(Claude Code, Codex) so they can check for existing components before
writing new code.

Verticalized on LexNotify by decision (2026-07-28); the code is generic
enough that a second instance could point --repo-root at another repo
without any changes here.
"""
from __future__ import annotations
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .manifest import load_manifest, ManifestError, ProjectManifest

mcp = FastMCP("lexnotify-map")

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


@mcp.tool()
def find_component(query: str, limit: int = 20) -> list[dict]:
    """Search architecture-map components by substring in path or exports.

    Use BEFORE writing any new helper, route, or component to confirm
    something similar doesn't already exist. Case-insensitive.

    Args:
        query: search term (e.g. "chat", "notification", "getOrCreate")
        limit: max results to return (default 20)

    Returns:
        List of {path, exports, layer} that match.
    """
    data = _read_map()
    q = query.lower()
    results = []
    for c in data.get("components", []):
        if q in c["path"].lower() or any(q in e.lower() for e in c.get("exports", [])):
            results.append(c)
            if len(results) >= limit:
                break
    return results


@mcp.tool()
def component_detail(path: str) -> dict:
    """Return the full architecture-map entry for a component by exact path.

    Args:
        path: file path relative to repo root (e.g. "src/lib/case-chat.ts")

    Returns:
        {path, exports, layer}, or {"error": "..."} if not found.
    """
    data = _read_map()
    for c in data.get("components", []):
        if c["path"] == path:
            return c
    return {"error": f"component not found: {path}"}


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


@mcp.tool()
def map_status() -> dict:
    """Return architecture-map metadata: when it was generated, from which
    commit, coverage, and component count. Use to judge whether the map
    might be stale before trusting an answer from the other tools.

    Returns:
        {generatedAt, sourceSha, coverage, componentCount, extractionMethod}
    """
    data = _read_map()
    return {
        "generatedAt": data.get("generatedAt"),
        "sourceSha": data.get("sourceSha"),
        "coverage": data.get("coverage"),
        "componentCount": len(data.get("components", [])),
        "extractionMethod": data.get("extractionMethod"),
    }


def serve(repo_root: Path) -> None:
    """Entry point called by `aak mcp serve --repo-root <path>`."""
    global _repo_root
    _repo_root = Path(repo_root).resolve()
    load_manifest(_repo_root)  # fail fast if the manifest is missing/broken
    mcp.run()
