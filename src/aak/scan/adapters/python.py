"""Python language adapter for the architecture scanner.

Regex-based (same philosophy as the TypeScript adapter, not an AST parse):
detects module-level `def`/`class` (column-0 indentation). When a module
declares `__all__`, that list is trusted as-is as the public surface
(including names re-exported from elsewhere that the regex itself wouldn't
find); otherwise every non-underscore-prefixed top-level def/class counts.
"""
import re
from pathlib import Path

from ..core import LanguageAdapter

EXPORT_DEF_RE = re.compile(r"^def\s+(\w+)\s*\(", re.MULTILINE)
EXPORT_CLASS_RE = re.compile(r"^class\s+(\w+)\s*[:\(]", re.MULTILINE)
ALL_RE = re.compile(r"^__all__\s*=\s*\[([^\]]*)\]", re.MULTILINE)


def _parse_all(raw: str) -> set[str]:
    return {item.strip(" \t\n'\"") for item in raw.split(",") if item.strip()}


def infer_layer(rel_path: str) -> str:
    """First path segment under the source root as the layer - a reasonable
    default for the common "monorepo of independent scripts/bots" Python
    layout (each top-level folder is its own semi-independent component),
    with `shared/` called out explicitly since it's the one folder name
    that consistently means "cross-cutting library code" in that layout."""
    parts = rel_path.split("/")
    if len(parts) < 2:
        return "other"
    first = parts[0]
    return "lib/shared" if first == "shared" else first


class PythonAdapter(LanguageAdapter):
    name = "python"
    file_globs = ("*.py",)
    exclude_suffixes = ("_test.py",)
    extraction_method = "phase2-regex-scan-of-source"

    def should_skip(self, rel_path: str, path: Path) -> bool:
        return path.name.startswith("test_")

    def scan_file(self, path: Path, rel_path: str) -> dict | None:
        text = path.read_text(encoding="utf-8", errors="replace")

        all_match = ALL_RE.search(text)
        if all_match:
            exports = sorted(_parse_all(all_match.group(1)))
        else:
            names = set(EXPORT_DEF_RE.findall(text)) | set(EXPORT_CLASS_RE.findall(text))
            exports = sorted(n for n in names if not n.startswith("_"))

        if not exports:
            return None
        return {"path": rel_path, "exports": exports, "layer": infer_layer(rel_path)}

    def coverage_text(self, scanned_roots: list[str]) -> str:
        roots_str = ", ".join(scanned_roots)
        return (
            f"Real scan of every .py file under sourceRoots ({roots_str}), excluding "
            "test_*.py/*_test.py. Extracts module-level def/class (column-0 indentation) "
            "via structured regex, not a full Python AST parse. When a module declares "
            "__all__, that list is trusted as-is as the export surface (including "
            "re-exported names the regex itself wouldn't find); otherwise every "
            "non-underscore-prefixed top-level def/class is treated as exported. Methods "
            "of a class, and names imported and used only internally, are not resolved "
            "individually."
        )
