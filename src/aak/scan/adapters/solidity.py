"""Solidity heuristic extraction of public contract capabilities.

Patterns target fictional contract fixtures, not a complete Solidity AST.
"""
import re
from pathlib import Path

from ..core import LanguageAdapter

EXCLUDE_SUFFIXES = (".t.sol", ".s.sol")
# Vendored dependencies (forge install / npm) and Foundry/Hardhat build
# output -- not in core.py's generic EXCLUDE_DIR_PARTS, which doesn't know
# about these Solidity-toolchain-specific directory names.
EXCLUDE_PATH_SEGMENTS = {"lib", "out", "cache", "artifacts", "typechain-types"}

EXPORT_CONTRACT_RE = re.compile(
    r"^(?:abstract\s+)?(?:contract|interface|library)\s+(\w+)", re.MULTILINE
)
CONTRACT_START_RE = re.compile(r"^(?:abstract\s+)?(?:contract|interface|library)\s+(\w+)")
EVENT_RE = re.compile(r"^\s+event\s+(\w+)\s*\(")
FUNCTION_RE = re.compile(r"^\s+function\s+(\w+)\s*\(")
VISIBILITY_RE = re.compile(r"\b(private|internal)\b")

# Function signatures can wrap across multiple lines, and in Solidity the
# visibility modifier comes *after* the parameter list, not before the name
# (unlike TS/Rust) -- so a single-line prefix regex can't tell public/
# external apart from private/internal. Join lines from the `function` match
# up to the first `{`/`;` (bounded window) and check visibility on that.
SIGNATURE_WINDOW = 15


def _extract_contract_body_names(text: str) -> set[str]:
    lines = text.splitlines()
    names: set[str] = set()
    in_contract = False
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not in_contract:
            if CONTRACT_START_RE.match(line):
                in_contract = True
            i += 1
            continue
        if line and not line[0].isspace():
            in_contract = False
            i += 1
            continue
        ev = EVENT_RE.match(line)
        if ev:
            names.add(ev.group(1))
            i += 1
            continue
        fn = FUNCTION_RE.match(line)
        if fn:
            j = i
            while j < n and "{" not in lines[j] and ";" not in lines[j] and (j - i) < SIGNATURE_WINDOW:
                j += 1
            signature = " ".join(lines[i:j + 1]) if j < n else lines[i]
            if not VISIBILITY_RE.search(signature):
                names.add(fn.group(1))
            i = j + 1
            continue
        i += 1
    return names


def infer_layer(rel_path: str) -> str:
    parts = rel_path.split("/")
    if len(parts) < 2:
        return "other"
    first = parts[0]
    return "lib/shared" if first == "shared" else first


class SolidityAdapter(LanguageAdapter):
    name = "solidity"
    file_globs = ("*.sol",)
    exclude_suffixes = EXCLUDE_SUFFIXES
    extraction_method = "phase2-regex-scan-of-source"

    def should_skip(self, rel_path: str, path: Path) -> bool:
        return bool(EXCLUDE_PATH_SEGMENTS & set(rel_path.split("/")[:-1]))

    def scan_file(self, path: Path, rel_path: str) -> dict | None:
        text = path.read_text(encoding="utf-8", errors="replace")

        exports = set(EXPORT_CONTRACT_RE.findall(text))
        exports.update(_extract_contract_body_names(text))

        if not exports:
            return None
        return {"path": rel_path, "exports": sorted(exports), "layer": infer_layer(rel_path)}

    def coverage_text(self, scanned_roots: list[str]) -> str:
        roots_str = ", ".join(scanned_roots)
        return (
            f"Real scan of every .sol file under sourceRoots ({roots_str}), excluding "
            "*.t.sol/*.s.sol (Foundry tests/scripts) and paths under lib/out/cache/"
            "artifacts/typechain-types (vendored dependencies and build output). "
            "Extracts contract/interface/library names, plus event names and "
            "public/external function names declared inside them, via structured "
            "regex, not a full Solidity parse. Visibility is checked by joining a "
            "function's signature lines up to its first '{' or ';' (bounded window) "
            "and looking for 'private'/'internal', since Solidity's visibility "
            "modifier comes after the parameter list, not before the function name. "
            "Structs, errors, modifiers, and state variables are not extracted."
        )
