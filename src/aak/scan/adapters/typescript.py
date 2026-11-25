"""TypeScript/Next.js heuristic extraction of module exports and public methods.

Coverage is declared by the adapter; this is not a semantic TypeScript compiler.
"""
import re
from pathlib import Path

from ..core import LanguageAdapter

EXCLUDE_SUFFIXES = (".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", ".d.ts")

# Next.js App Router special-convention files: one per route, by definition
# not reusable helpers - excluded so the map stays focused on its stated
# purpose (reuse before reinventing), not diluted with hundreds of one-off
# page entries. Route handlers (route.ts) are NOT excluded.
NEXTJS_CONVENTION_STEMS = {
    "page", "layout", "loading", "error", "not-found", "template", "default",
    "opengraph-image", "twitter-image", "icon", "apple-icon", "sitemap", "robots",
}

# Order matters: more specific path prefixes first.
LAYER_MAP = [
    ("src/lib/supabase/", "lib/core"),
    ("src/lib/api-", "lib/core"),
    ("src/lib/logger.ts", "lib/core"),
    ("src/lib/messages.ts", "lib/core"),
    ("src/lib/fetch-client.ts", "lib/client"),
    ("src/lib/org", "lib/org"),
    ("src/lib/case", "lib/case"),
    ("src/lib/agent-jobs.ts", "lib/queue"),
    ("src/lib/enqueue-", "lib/queue"),
    ("src/lib/enrichment.ts", "lib/domain"),
    ("src/lib/cron/", "lib/cron"),
    ("src/lib/", "lib"),
    ("src/domain/", "domain"),
    ("src/contracts/", "contracts"),
    ("src/services/", "services"),
    ("src/application/", "application"),
    ("src/overlay/", "frontend/overlay"),
    ("src/contexts/", "frontend/context"),
    ("src/components/", "frontend/component"),
    ("app/api/", "api"),  # further specialized below using the 2nd path segment
]

EXPORT_FUNCTION_RE = re.compile(
    r"^export\s+(?:default\s+)?(?:async\s+)?function\s+(\w+)", re.MULTILINE
)
EXPORT_CONST_RE = re.compile(r"^export\s+(?:const|let|var)\s+(\w+)", re.MULTILINE)
EXPORT_CLASS_RE = re.compile(r"^export\s+(?:default\s+)?(?:abstract\s+)?class\s+(\w+)", re.MULTILINE)
EXPORT_INTERFACE_RE = re.compile(r"^export\s+interface\s+(\w+)", re.MULTILINE)
EXPORT_TYPE_RE = re.compile(r"^export\s+type\s+(\w+)", re.MULTILINE)
EXPORT_ENUM_RE = re.compile(r"^export\s+(?:const\s+)?enum\s+(\w+)", re.MULTILINE)
EXPORT_DEFAULT_IDENT_RE = re.compile(r"^export\s+default\s+(\w+)\s*;", re.MULTILINE)
EXPORT_DEFAULT_ANCHORED_RE = re.compile(r"^export\s+default\b", re.MULTILINE)
REEXPORT_STAR_RE = re.compile(r"^export\s+\*\s+from\s+['\"]([^'\"]+)['\"]", re.MULTILINE)
REEXPORT_NAMED_RE = re.compile(
    r"^export\s+\{([^}]*)\}\s+from\s+['\"]([^'\"]+)['\"]", re.MULTILINE
)
EXPORT_NAMED_LOCAL_RE = re.compile(r"^export\s+\{([^}]*)\}\s*;", re.MULTILINE)

ROUTE_METHOD_RE = re.compile(
    r"^export\s+(?:const|async\s+function)\s+(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b",
    re.MULTILINE,
)

# Class-method extraction (issue #35): the scanner otherwise only ever sees
# top-level `export ...` statements, so a method like EventService.publish
# never shows up when only the class *instance* is exported (`export default
# eventService`), not the class itself - a real, confirmed false-negative in
# verify_references against synthetic duplication incidents. This
# is line-based, not a brace-depth parser: a class body is assumed to start
# at a `class X {` line and end at the first following non-indented,
# non-blank line (matches this codebase's consistent 2-space, same-line-
# brace style - same level of approximation as the rest of this adapter).
CLASS_START_RE = re.compile(r"^(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(\w+)\b")
# Exactly 2-space indent = a direct class member. private/protected members
# are excluded implicitly: those keywords aren't in the accepted modifier
# list below, so `\s*\(` never lines up right after them. `constructor` is
# excluded explicitly by name below (it's never a citable capability).
CLASS_METHOD_RE = re.compile(r"^  (?:public\s+)?(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?(\w+)\s*\(")


def _extract_class_method_names(text: str) -> set[str]:
    names: set[str] = set()
    in_class = False
    for line in text.splitlines():
        if not in_class:
            if CLASS_START_RE.match(line):
                in_class = True
            continue
        if line and not line[0].isspace():
            in_class = False
            continue
        m = CLASS_METHOD_RE.match(line)
        if m and m.group(1) != "constructor":
            names.add(m.group(1))
    return names


def _parse_named_list(raw: str) -> list[str]:
    """`{ A, B as C, type D }` -> ['A', 'C', 'D'] (the locally-visible/exported name)."""
    names = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        item = re.sub(r"^type\s+", "", item)
        if " as " in item:
            item = item.split(" as ", 1)[1].strip()
        names.append(item)
    return names


def infer_layer(rel_path: str) -> str:
    if rel_path.startswith("app/api/"):
        segments = rel_path.split("/")
        if len(segments) > 2:
            return f"api/{segments[2]}"
        return "api"
    for prefix, layer in LAYER_MAP:
        if rel_path.startswith(prefix):
            return layer
    return "other"


class TypeScriptAdapter(LanguageAdapter):
    name = "typescript"
    file_globs = ("*.ts", "*.tsx")
    exclude_suffixes = EXCLUDE_SUFFIXES
    extraction_method = "phase2-regex-scan-of-source"

    def should_skip(self, rel_path: str, path: Path) -> bool:
        return (
            rel_path.startswith("app/")
            and not rel_path.endswith("/route.ts")
            and path.stem in NEXTJS_CONVENTION_STEMS
        )

    def scan_file(self, path: Path, rel_path: str) -> dict | None:
        text = path.read_text(encoding="utf-8", errors="replace")

        if rel_path.startswith("app/api/") and rel_path.endswith("route.ts"):
            methods = sorted(set(ROUTE_METHOD_RE.findall(text)))
            if not methods:
                return None
            return {"path": rel_path, "exports": methods, "layer": infer_layer(rel_path)}

        exports = set()
        exports.update(EXPORT_FUNCTION_RE.findall(text))
        exports.update(EXPORT_CONST_RE.findall(text))
        exports.update(EXPORT_CLASS_RE.findall(text))
        exports.update(EXPORT_INTERFACE_RE.findall(text))
        exports.update(EXPORT_TYPE_RE.findall(text))
        exports.update(EXPORT_ENUM_RE.findall(text))
        exports.update(EXPORT_DEFAULT_IDENT_RE.findall(text))
        if EXPORT_DEFAULT_ANCHORED_RE.search(text) and not EXPORT_DEFAULT_IDENT_RE.search(text):
            exports.add("default")
        for raw_list in EXPORT_NAMED_LOCAL_RE.findall(text):
            exports.update(_parse_named_list(raw_list))
        exports.update(_extract_class_method_names(text))

        re_exports = sorted(set(REEXPORT_STAR_RE.findall(text)) | {p for _, p in REEXPORT_NAMED_RE.findall(text)})

        if not exports and not re_exports:
            return None

        component = {"path": rel_path, "exports": sorted(exports), "layer": infer_layer(rel_path)}
        if re_exports:
            component["reExportsFrom"] = re_exports
        return component

    def coverage_text(self, scanned_roots: list[str]) -> str:
        roots_str = ", ".join(scanned_roots)
        return (
            f"Real scan of every .ts/.tsx file under sourceRoots ({roots_str}), excluding "
            "tests and generated paths. Extracts module-level exports (function/const/class/"
            "interface/type/enum, including local 'export { X }' lists) via structured "
            "regex, not a full TS AST parse. app/api/**/route.ts is special-cased to list "
            "only exported HTTP method handlers. Public methods of any class body found in "
            "the file (2-space-indented direct members, excluding constructor/private/"
            "protected) are also recorded as bare export entries, even when only an "
            "instance of the class is exported - not the class itself - so method-level "
            "citations like EventService.publish can be verified. 'export *'/'export {X} "
            "from' are recorded as reExportsFrom (not resolved recursively to the original "
            "file)."
        )
