"""Generic scanner, deterministic JSON and source-drift verification.

Language-specific extraction belongs to adapters. Markdown regeneration updates
only the designated generated section.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

VOLATILE_FIELDS = {"generatedAt", "sourceSha"}
EXCLUDE_DIR_PARTS = {
    "node_modules", ".next", "coverage", "dist", "build",
    "__pycache__", ".venv", "venv", ".git",
}

SECTION_HEADER = "## 1. Quick-reference table"
HEADING_RE = re.compile(r"^#{1,6}\s")


class LanguageAdapter(ABC):
    """Contract a language adapter implements to plug into the scanner core."""

    name: str
    file_globs: tuple[str, ...]
    exclude_suffixes: tuple[str, ...] = ()
    extraction_method: str

    def should_skip(self, rel_path: str, path: Path) -> bool:
        """Extra language-specific skip logic beyond EXCLUDE_DIR_PARTS/exclude_suffixes."""
        return False

    @abstractmethod
    def scan_file(self, path: Path, rel_path: str) -> dict | None:
        """Returns {"path", "exports", "layer", ["reExportsFrom"]}, or None if nothing exported."""

    @abstractmethod
    def coverage_text(self, scanned_roots: list[str]) -> str:
        """Human-readable description of what this scan actually covers/misses."""


def scan_repo(repo_root: Path, source_roots: list[str], adapter: LanguageAdapter) -> tuple[list[dict], list[str]]:
    components = []
    scanned_roots = []
    for root_name in source_roots:
        root = repo_root / root_name
        if not root.is_dir():
            continue
        scanned_roots.append(root_name)
        for glob in adapter.file_globs:
            for path in sorted(root.rglob(glob)):
                if any(part in EXCLUDE_DIR_PARTS for part in path.parts):
                    continue
                if path.name.endswith(adapter.exclude_suffixes):
                    continue
                rel_path = str(path.relative_to(repo_root)).replace("\\", "/")
                if adapter.should_skip(rel_path, path):
                    continue
                component = adapter.scan_file(path, rel_path)
                if component:
                    components.append(component)
    return components, scanned_roots


def git_head_sha(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _stable(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in VOLATILE_FIELDS}


def build_doc(
    repo_root: Path, repo_id: str, components: list[dict], scanned_roots: list[str], adapter: LanguageAdapter
) -> dict:
    return {
        "schemaVersion": "1.0",
        "repoId": repo_id,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceSha": git_head_sha(repo_root),
        "extractionMethod": adapter.extraction_method,
        "coverage": adapter.coverage_text(scanned_roots),
        "components": components,
    }


def render_table(components: list[dict]) -> str:
    lines = [SECTION_HEADER, "", "| File | Key Exports | Layer |", "|------|-------------|-------|"]
    for c in sorted(components, key=lambda x: x["path"]):
        exports = c["exports"] or [f"(re-exports from {r})" for r in c.get("reExportsFrom", [])]
        exports_str = ", ".join(f"`{e}`" for e in exports) if c["exports"] else ", ".join(exports)
        lines.append(f"| `{c['path']}` | {exports_str} | {c['layer']} |")
    return "\n".join(lines) + "\n"


def regenerate_md_section1(md_text: str, components: list[dict], md_path_for_errors: str = "<markdown>") -> str:
    """Replaces only the block from SECTION_HEADER up to (not including) the
    next Markdown heading of any level. Everything before and after is
    preserved byte for byte."""
    lines = md_text.splitlines(keepends=True)
    start = None
    end = len(lines)
    for i, line in enumerate(lines):
        if start is None and line.rstrip("\n") == SECTION_HEADER:
            start = i
            continue
        if start is not None and i > start and HEADING_RE.match(line):
            end = i
            break
    if start is None:
        raise ValueError(f"'{SECTION_HEADER}' not found in {md_path_for_errors}")
    new_section = render_table(components) + "\n"
    return "".join(lines[:start]) + new_section + "".join(lines[end:])


def run_scan(
    repo_root: Path,
    repo_id: str,
    source_roots: list[str],
    adapter: LanguageAdapter,
    out_json: Path,
    md_path: Path,
    check_mode: bool,
) -> int:
    """Shared scan -> build doc -> (--check drift | write) flow. Returns exit code."""
    components, scanned_roots = scan_repo(repo_root, source_roots, adapter)
    doc = build_doc(repo_root, repo_id, components, scanned_roots, adapter)

    old_md = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""
    new_md = regenerate_md_section1(old_md, components, str(md_path)) if old_md else None

    if check_mode:
        if not out_json.is_file():
            print(f"DRIFT: {out_json} does not exist - run the scanner and commit it", file=sys.stderr)
            return 1
        committed = json.loads(out_json.read_text(encoding="utf-8"))
        if _stable(committed) != _stable(doc):
            print(
                f"DRIFT: {out_json} does not match a fresh scan of the source tree. "
                f"Run the scanner and commit the result.",
                file=sys.stderr,
            )
            return 1
        if new_md is not None and new_md != old_md:
            print(
                f"DRIFT: {md_path} section 1 does not match a fresh regeneration from "
                f"the committed JSON. Run the scanner and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {out_json} and {md_path} section 1 match a fresh scan ({len(components)} components).")
        return 0

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    if new_md is not None:
        md_path.write_text(new_md, encoding="utf-8")
    print(f"wrote {out_json} and regenerated {md_path} section 1 : {len(components)} components")
    return 0
