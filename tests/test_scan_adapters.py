"""Tests for the TypeScript and Python scanner adapters."""
from pathlib import Path

from aak.scan.adapters.python import PythonAdapter
from aak.scan.adapters.typescript import TypeScriptAdapter


def _write(tmp_path: Path, rel_path: str, content: str) -> Path:
    p = tmp_path / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


class TestPythonAdapter:
    def setup_method(self):
        self.adapter = PythonAdapter()

    def test_module_level_def_and_class(self, tmp_path):
        p = _write(tmp_path, "shared/foo.py", "def do_thing():\n    pass\n\n\nclass Widget:\n    pass\n")
        result = self.adapter.scan_file(p, "shared/foo.py")
        assert result == {"path": "shared/foo.py", "exports": ["Widget", "do_thing"], "layer": "lib/shared"}

    def test_underscore_prefixed_names_are_private(self, tmp_path):
        p = _write(tmp_path, "strategies/kairi/bot.py", "def public_fn():\n    pass\n\n\ndef _private_fn():\n    pass\n")
        result = self.adapter.scan_file(p, "strategies/kairi/bot.py")
        assert result["exports"] == ["public_fn"]
        assert result["layer"] == "strategies"

    def test_dunder_all_is_trusted_as_is(self, tmp_path):
        p = _write(
            tmp_path,
            "shared/api.py",
            "from .internal import helper\n\n__all__ = ['helper', 'public_fn']\n\n\ndef public_fn():\n    pass\n",
        )
        result = self.adapter.scan_file(p, "shared/api.py")
        # 'helper' is only imported, never defined here - __all__ still wins.
        assert result["exports"] == ["helper", "public_fn"]

    def test_file_with_no_module_level_exports_returns_none(self, tmp_path):
        p = _write(tmp_path, "scripts/run.py", "if __name__ == '__main__':\n    print('hi')\n")
        assert self.adapter.scan_file(p, "scripts/run.py") is None

    def test_should_skip_test_files(self, tmp_path):
        p = _write(tmp_path, "shared/test_foo.py", "def test_x(): pass\n")
        assert self.adapter.should_skip("shared/test_foo.py", p) is True


class TestTypeScriptAdapter:
    def setup_method(self):
        self.adapter = TypeScriptAdapter()

    def test_export_function_const_class(self, tmp_path):
        p = _write(
            tmp_path,
            "src/lib/foo.ts",
            "export function doThing() {}\nexport const X = 1;\nexport class Widget {}\n",
        )
        result = self.adapter.scan_file(p, "src/lib/foo.ts")
        assert result["exports"] == ["Widget", "X", "doThing"]
        assert result["layer"] == "lib"

    def test_route_ts_lists_only_http_methods(self, tmp_path):
        p = _write(
            tmp_path,
            "app/api/cases/route.ts",
            "export const GET = apiHandler(async () => {});\nexport const POST = apiHandler(async () => {});\n",
        )
        result = self.adapter.scan_file(p, "app/api/cases/route.ts")
        assert result == {"path": "app/api/cases/route.ts", "exports": ["GET", "POST"], "layer": "api/cases"}

    def test_reexport_star_recorded_not_resolved(self, tmp_path):
        p = _write(tmp_path, "src/lib/barrel.ts", "export * from './impl';\n")
        result = self.adapter.scan_file(p, "src/lib/barrel.ts")
        assert result["exports"] == []
        assert result["reExportsFrom"] == ["./impl"]

    def test_should_skip_nextjs_convention_files(self, tmp_path):
        p = _write(tmp_path, "app/dashboard/page.tsx", "export default function Page() { return null; }\n")
        assert self.adapter.should_skip("app/dashboard/page.tsx", p) is True

    def test_should_not_skip_route_ts_even_under_app(self, tmp_path):
        p = _write(tmp_path, "app/api/health/route.ts", "export async function GET() {}\n")
        assert self.adapter.should_skip("app/api/health/route.ts", p) is False

    def test_class_method_recorded_even_when_only_instance_is_exported(self, tmp_path):
        """Reproduces the real EventService/publish case from issue #35: the
        class itself is never exported, only an instance of it is."""
        content = (
            "class EventService {\n"
            "  async publish(input) {\n"
            "    return null;\n"
            "  }\n"
            "\n"
            "  private isPoisonMessage(x) {\n"
            "    return false;\n"
            "  }\n"
            "\n"
            "  constructor() {}\n"
            "}\n"
            "\n"
            "const eventService = new EventService();\n"
            "export default eventService;\n"
        )
        p = _write(tmp_path, "src/services/EventService.ts", content)
        result = self.adapter.scan_file(p, "src/services/EventService.ts")
        assert "publish" in result["exports"]
        assert "eventService" in result["exports"]
        assert "isPoisonMessage" not in result["exports"]
        assert "constructor" not in result["exports"]

    def test_class_methods_do_not_leak_past_the_class_body(self, tmp_path):
        content = (
            "class Widget {\n"
            "  render() {}\n"
            "}\n"
            "\n"
            "export function unrelated() {}\n"
        )
        p = _write(tmp_path, "src/lib/widget.ts", content)
        result = self.adapter.scan_file(p, "src/lib/widget.ts")
        assert result["exports"] == ["render", "unrelated"]

    def test_class_method_extraction_coexists_with_top_level_exports(self, tmp_path):
        content = (
            "export const TOP_LEVEL = 1;\n"
            "\n"
            "class Service {\n"
            "  async run() {}\n"
            "  static staticHelper() {}\n"
            "}\n"
            "\n"
            "export const service = new Service();\n"
        )
        p = _write(tmp_path, "src/services/Service.ts", content)
        result = self.adapter.scan_file(p, "src/services/Service.ts")
        assert result["exports"] == ["TOP_LEVEL", "run", "service", "staticHelper"]
