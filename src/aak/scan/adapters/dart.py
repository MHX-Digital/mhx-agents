"""Dart/Flutter heuristic extraction of public declarations and class members.

Generated files and underscore-prefixed declarations are excluded.
"""
import re
from pathlib import Path

from ..core import LanguageAdapter

EXCLUDE_SUFFIXES = (".g.dart", ".freezed.dart", "_test.dart")

EXPORT_CLASS_RE = re.compile(r"^(?:abstract\s+)?class\s+(\w+)", re.MULTILINE)
EXPORT_MIXIN_RE = re.compile(r"^mixin\s+(\w+)", re.MULTILINE)
EXPORT_ENUM_RE = re.compile(r"^enum\s+(\w+)", re.MULTILINE)
EXPORT_TYPEDEF_RE = re.compile(r"^typedef\s+(\w+)", re.MULTILINE)
EXPORT_RE = re.compile(r"^export\s+'([^']+)'", re.MULTILINE)

# Lazy optional prefix so a return type (including nested generics like
# `Future<Response<T>>`) is skipped without needing to parse it -- tries
# the shortest prefix first, only expanding until a name is immediately
# followed by '('. The `(?=\S)` guard is load-bearing: the prefix charset
# includes `\s`, so without it the lazy group would happily swallow extra
# leading indentation and match statements nested deep inside a method body
# (an `if (...)`/`while (...)` reads exactly like "name-then-paren" too).
# Requiring a non-space character immediately after the anchor keeps this
# scoped to the line's actual first token. Deliberately does not handle
# generic methods/functions (`name<T>(...)`, no space before the '<') or
# getters/setters -- documented gap, not silently pretended away.
_NAME_RE = r"(?=\S)(?:[\w<>?,\s]+?\s+)?(\w+)\s*\("
EXPORT_FUNCTION_RE = re.compile(r"^" + _NAME_RE, re.MULTILINE)

CLASS_OR_MIXIN_START_RE = re.compile(r"^(?:abstract\s+)?(?:class|mixin)\s+(\w+)")
MEMBER_METHOD_RE = re.compile(r"^  (?:static\s+)?" + _NAME_RE)


def _extract_member_names(text: str) -> set[str]:
    """Members of a private class/mixin (`_Foo`) are skipped entirely, not
    just filtered by their own name. Unlike TypeScript (kit issue #35),
    where a non-exported class can still be reached through an exported
    instance, a Dart class whose *type* is library-private can't be
    referenced from outside at all -- there's no equivalent escape hatch.
    Confirmed against the real, ubiquitous `_FooState extends State<Foo>`
    pattern: its `build()` override is framework-invoked, never a citable
    reusable capability, even though the method name itself is public."""
    names: set[str] = set()
    in_body = False
    body_is_private = False
    for line in text.splitlines():
        if not in_body:
            m = CLASS_OR_MIXIN_START_RE.match(line)
            if m:
                in_body = True
                body_is_private = m.group(1).startswith("_")
            continue
        if line and not line[0].isspace():
            in_body = False
            continue
        if body_is_private:
            continue
        m = MEMBER_METHOD_RE.match(line)
        if m and not m.group(1).startswith("_"):
            names.add(m.group(1))
    return names


def infer_layer(rel_path: str) -> str:
    """First path segment under the scanned source root (typically `lib/`)
    - matches Flutter's real feature/layer folder convention confirmed
    against fictional module layouts: core/, design_system/, features/, routing/, shared/."""
    parts = rel_path.split("/")
    if len(parts) < 2:
        return "other"
    first = parts[0]
    return "lib/shared" if first == "shared" else first


class DartAdapter(LanguageAdapter):
    name = "dart"
    file_globs = ("*.dart",)
    exclude_suffixes = EXCLUDE_SUFFIXES
    extraction_method = "phase2-regex-scan-of-source"

    def scan_file(self, path: Path, rel_path: str) -> dict | None:
        text = path.read_text(encoding="utf-8", errors="replace")

        exports = set()
        exports.update(n for n in EXPORT_CLASS_RE.findall(text) if not n.startswith("_"))
        exports.update(n for n in EXPORT_MIXIN_RE.findall(text) if not n.startswith("_"))
        exports.update(n for n in EXPORT_ENUM_RE.findall(text) if not n.startswith("_"))
        exports.update(n for n in EXPORT_TYPEDEF_RE.findall(text) if not n.startswith("_"))
        exports.update(n for n in EXPORT_FUNCTION_RE.findall(text) if not n.startswith("_"))
        exports.update(_extract_member_names(text))

        re_exports = sorted(set(EXPORT_RE.findall(text)))

        if not exports and not re_exports:
            return None

        component = {"path": rel_path, "exports": sorted(exports), "layer": infer_layer(rel_path)}
        if re_exports:
            component["reExportsFrom"] = re_exports
        return component

    def coverage_text(self, scanned_roots: list[str]) -> str:
        roots_str = ", ".join(scanned_roots)
        return (
            f"Real scan of every .dart file under sourceRoots ({roots_str}), excluding "
            "*.g.dart/*.freezed.dart (codegen) and *_test.dart. Extracts top-level "
            "class/abstract class/mixin/enum/typedef, plus a best-effort match of "
            "top-level functions and class/mixin methods (return-type prefix, "
            "including nested generics, is skipped lazily rather than parsed) via "
            "structured regex, not a full Dart parse. Names starting with '_' are "
            "excluded (Dart's privacy convention), and members of a class/mixin whose "
            "own name starts with '_' are skipped entirely, not just filtered by their "
            "own name -- confirmed against the real `_FooState extends State<Foo>` "
            "pattern every StatefulWidget uses, where public-looking method names like "
            "`build()` are framework-invoked internals, not citable capability. Named "
            "constructors (`ClassName.named(...)`) are excluded (the '.' breaks the "
            "name match); default and factory constructors (`ClassName()`/`factory "
            "ClassName()`) can still match and add the class's own name again, which "
            "is harmless since that name is already present from the class export "
            "itself. Generic methods/functions (`name<T>(...)`) and getters/setters "
            "are not extracted. `export 'path.dart'` (with or without show/hide) is "
            "recorded as reExportsFrom, not resolved recursively."
        )
