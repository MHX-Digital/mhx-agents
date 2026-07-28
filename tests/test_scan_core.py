"""Tests for the language-agnostic scanner core (aak.scan.core)."""
from pathlib import Path

import pytest

from aak.scan.core import LanguageAdapter, regenerate_md_section1, render_table, scan_repo


class _FakeAdapter(LanguageAdapter):
    """Minimal adapter: any .txt file with non-empty content exports its own name."""

    name = "fake"
    file_globs = ("*.txt",)
    exclude_suffixes = ("_skip.txt",)
    extraction_method = "fake-test-method"

    def scan_file(self, path: Path, rel_path: str):
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return None
        return {"path": rel_path, "exports": [path.stem], "layer": "test"}

    def coverage_text(self, scanned_roots):
        return f"fake coverage over {scanned_roots}"


def test_scan_repo_respects_exclude_dirs_and_suffixes(tmp_path):
    root = tmp_path / "src"
    (root / "node_modules").mkdir(parents=True)
    (root / "node_modules" / "ignored.txt").write_text("x")
    (root).mkdir(exist_ok=True)
    (root / "real.txt").write_text("x")
    (root / "empty.txt").write_text("")
    (root / "thing_skip.txt").write_text("x")

    components, scanned_roots = scan_repo(tmp_path, ["src"], _FakeAdapter())

    assert scanned_roots == ["src"]
    paths = {c["path"] for c in components}
    assert paths == {"src/real.txt"}


def test_scan_repo_skips_nonexistent_source_root(tmp_path):
    components, scanned_roots = scan_repo(tmp_path, ["does-not-exist"], _FakeAdapter())
    assert components == []
    assert scanned_roots == []


def test_render_table_uses_reexports_when_no_direct_exports():
    components = [
        {"path": "b.ts", "exports": ["Foo"], "layer": "lib"},
        {"path": "a.ts", "exports": [], "layer": "lib", "reExportsFrom": ["./other"]},
    ]
    table = render_table(components)
    lines = table.splitlines()
    # sorted by path: a.ts before b.ts
    assert "a.ts" in lines[4]
    assert "(re-exports from ./other)" in lines[4]
    assert "b.ts" in lines[5]
    assert "`Foo`" in lines[5]


def test_regenerate_md_section1_preserves_surrounding_content():
    md = (
        "# Intro\n\nSome prose.\n\n"
        "## 1. Quick-reference table\n\n"
        "| File | Key Exports | Layer |\n|------|-------------|-------|\n"
        "| `old.ts` | `Old` | lib |\n\n"
        "### Multi-tenant RPC functions\n\nKept as-is.\n\n"
        "## 2. Helpers\n\nAlso kept.\n"
    )
    components = [{"path": "new.ts", "exports": ["New"], "layer": "lib"}]
    result = regenerate_md_section1(md, components, "test.md")

    assert "# Intro" in result
    assert "Some prose." in result
    assert "`new.ts`" in result
    assert "`old.ts`" not in result
    assert "### Multi-tenant RPC functions" in result
    assert "Kept as-is." in result
    assert "## 2. Helpers" in result
    assert "Also kept." in result


def test_regenerate_md_section1_raises_if_header_missing():
    with pytest.raises(ValueError, match="Quick-reference table"):
        regenerate_md_section1("# no matching header here\n", [], "test.md")
