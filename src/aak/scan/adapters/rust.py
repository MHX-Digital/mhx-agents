"""Rust language adapter for the architecture scanner.

Regex-based (same philosophy as the TypeScript/Python adapters, not a full
syn/AST parse). Confirmed against real source (Quantitativo's MEV bot,
statum-fi's Anchor/keeper crates) before writing these patterns: idiomatic
Rust (rustfmt default) uses 4-space indentation and puts `pub` items either
at module top level or as `pub fn` methods inside `impl Type { ... }` blocks
-- the same "capability lives inside a member block, not a top-level
export" shape that TypeScript's class-method gap (kit issue #35) had.
Handled here from the start instead of needing a follow-up fix.
"""
import re
from pathlib import Path

from ..core import LanguageAdapter

EXPORT_FN_RE = re.compile(r"^pub\s+(?:async\s+)?fn\s+(\w+)", re.MULTILINE)
EXPORT_STRUCT_RE = re.compile(r"^pub\s+struct\s+(\w+)", re.MULTILINE)
EXPORT_ENUM_RE = re.compile(r"^pub\s+enum\s+(\w+)", re.MULTILINE)
EXPORT_TRAIT_RE = re.compile(r"^pub\s+trait\s+(\w+)", re.MULTILINE)
EXPORT_CONST_RE = re.compile(r"^pub\s+const\s+(\w+)", re.MULTILINE)
EXPORT_STATIC_RE = re.compile(r"^pub\s+static\s+(?:mut\s+)?(\w+)", re.MULTILINE)
EXPORT_TYPE_RE = re.compile(r"^pub\s+type\s+(\w+)", re.MULTILINE)

REEXPORT_GLOB_RE = re.compile(r"^pub\s+use\s+([\w:]+)::\*\s*;", re.MULTILINE)
REEXPORT_LIST_RE = re.compile(r"^pub\s+use\s+[\w:]+::\{([^}]*)\}\s*;", re.MULTILINE)
REEXPORT_SINGLE_RE = re.compile(r"^pub\s+use\s+[\w:]+::(\w+)\s*;", re.MULTILINE)

# `impl Type { ... }` and `impl Trait for Type { ... }` (with optional
# generics on either side) both end in the type name right before `{`.
IMPL_START_RE = re.compile(r"^impl(?:<[^>]*>)?\s+(?:[\w:]+(?:<[^>]*>)?\s+for\s+)?([\w:]+)")
# Exactly 4-space indent = a direct member of the impl block. `pub(crate)`/
# `pub(super)` are excluded implicitly: there's no space between `pub` and
# `(`, so `pub\s+fn` never matches them.
IMPL_METHOD_RE = re.compile(r"^ {4}pub\s+(?:async\s+)?fn\s+(\w+)\s*[(<]")


def _parse_named_list(raw: str) -> list[str]:
    """`{A, B as C}` -> ['A', 'C'] (the locally-visible/imported name)."""
    names = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if " as " in item:
            item = item.split(" as ", 1)[1].strip()
        names.append(item)
    return names


def _extract_impl_method_names(text: str) -> set[str]:
    names: set[str] = set()
    in_impl = False
    for line in text.splitlines():
        if not in_impl:
            if IMPL_START_RE.match(line):
                in_impl = True
            continue
        if line and not line[0].isspace():
            in_impl = False
            continue
        m = IMPL_METHOD_RE.match(line)
        if m:
            names.add(m.group(1))
    return names


def infer_layer(rel_path: str) -> str:
    """First path segment under the scanned source root - matches how this
    portfolio's Rust projects are organized (Quantitativo's apps/bot/src/{data,
    decision,execution,ledger,alerts}/, statum-fi's crates/*/src/)."""
    parts = rel_path.split("/")
    if len(parts) < 2:
        return "other"
    first = parts[0]
    return "lib/shared" if first == "shared" else first


class RustAdapter(LanguageAdapter):
    name = "rust"
    file_globs = ("*.rs",)
    extraction_method = "phase2-regex-scan-of-source"

    def should_skip(self, rel_path: str, path: Path) -> bool:
        return "tests" in rel_path.split("/")[:-1]

    def scan_file(self, path: Path, rel_path: str) -> dict | None:
        text = path.read_text(encoding="utf-8", errors="replace")

        exports = set()
        exports.update(EXPORT_FN_RE.findall(text))
        exports.update(EXPORT_STRUCT_RE.findall(text))
        exports.update(EXPORT_ENUM_RE.findall(text))
        exports.update(EXPORT_TRAIT_RE.findall(text))
        exports.update(EXPORT_CONST_RE.findall(text))
        exports.update(EXPORT_STATIC_RE.findall(text))
        exports.update(EXPORT_TYPE_RE.findall(text))
        exports.update(REEXPORT_SINGLE_RE.findall(text))
        for raw_list in REEXPORT_LIST_RE.findall(text):
            exports.update(_parse_named_list(raw_list))
        exports.update(_extract_impl_method_names(text))

        re_exports = sorted(set(REEXPORT_GLOB_RE.findall(text)))

        if not exports and not re_exports:
            return None

        component = {"path": rel_path, "exports": sorted(exports), "layer": infer_layer(rel_path)}
        if re_exports:
            component["reExportsFrom"] = re_exports
        return component

    def coverage_text(self, scanned_roots: list[str]) -> str:
        roots_str = ", ".join(scanned_roots)
        return (
            f"Real scan of every .rs file under sourceRoots ({roots_str}), excluding "
            "paths under a 'tests' segment (integration tests). Extracts module-level "
            "pub fn/struct/enum/trait/const/static/type via structured regex, not a "
            "syn/AST parse. pub(crate)/pub(super) items are excluded (only bare pub "
            "counts as a public export). Public methods of any impl block (impl Type / "
            "impl Trait for Type, 4-space-indented direct members) are also recorded as "
            "bare export entries, same rationale as TypeScript class methods (kit issue "
            "#35) -- most real capability in idiomatic Rust lives in impl blocks, not "
            "top-level fn. 'pub use path::*' is recorded as reExportsFrom (not resolved "
            "recursively); 'pub use path::{A, B}' and 'pub use path::Single' add those "
            "names directly to this module's exports."
        )
