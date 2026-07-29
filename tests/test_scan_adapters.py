"""Tests for the TypeScript, Python, Rust, Solidity, and Dart scanner adapters."""
from pathlib import Path

from aak.scan.adapters.python import PythonAdapter
from aak.scan.adapters.typescript import TypeScriptAdapter
from aak.scan.adapters.rust import RustAdapter
from aak.scan.adapters.solidity import SolidityAdapter
from aak.scan.adapters.dart import DartAdapter


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

class TestRustAdapter:
    def setup_method(self):
        self.adapter = RustAdapter()

    def test_top_level_pub_items(self, tmp_path):
        content = (
            "pub struct ExecutionOrder {\n"
            "    pub size_eth: f64,\n"
            "}\n"
            "\n"
            "pub fn evaluate_all() {}\n"
            "\n"
            "pub(crate) fn internal_helper() {}\n"
        )
        p = _write(tmp_path, "decision/engine.rs", content)
        result = self.adapter.scan_file(p, "decision/engine.rs")
        assert result["exports"] == ["ExecutionOrder", "evaluate_all"]
        assert result["layer"] == "decision"

    def test_impl_block_public_methods_recorded(self, tmp_path):
        """Reproduces the real Quantitativo pattern: DecisionEngine::new /
        ::evaluate live inside `impl DecisionEngine { ... }`, never as
        top-level `pub fn` -- the same gap TS class methods had (issue #35),
        handled here from the start."""
        content = (
            "pub struct DecisionEngine {\n"
            "    total_capital_usd: f64,\n"
            "}\n"
            "\n"
            "impl DecisionEngine {\n"
            "    pub fn new(config: &Config) -> Self {\n"
            "        Self { total_capital_usd: 10_000.0 }\n"
            "    }\n"
            "\n"
            "    fn private_helper(&self) {}\n"
            "\n"
            "    pub fn evaluate(&self, opportunities: Vec<Opportunity>) -> Vec<ExecutionOrder> {\n"
            "        Vec::new()\n"
            "    }\n"
            "}\n"
        )
        p = _write(tmp_path, "decision/engine.rs", content)
        result = self.adapter.scan_file(p, "decision/engine.rs")
        assert result["exports"] == ["DecisionEngine", "evaluate", "new"]
        assert "private_helper" not in result["exports"]

    def test_pub_use_reexports(self, tmp_path):
        content = "pub use crate::foo::Bar;\npub use crate::baz::*;\n"
        p = _write(tmp_path, "lib.rs", content)
        result = self.adapter.scan_file(p, "lib.rs")
        assert result["exports"] == ["Bar"]
        assert result["reExportsFrom"] == ["crate::baz"]

    def test_should_skip_integration_tests_dir(self, tmp_path):
        p = _write(tmp_path, "crates/backtest/tests/smoke.rs", "pub fn helper() {}\n")
        assert self.adapter.should_skip("crates/backtest/tests/smoke.rs", p) is True

    def test_file_with_no_pub_items_returns_none(self, tmp_path):
        p = _write(tmp_path, "internal.rs", "fn private_only() {}\n")
        assert self.adapter.scan_file(p, "internal.rs") is None


class TestSolidityAdapter:
    def setup_method(self):
        self.adapter = SolidityAdapter()

    def test_contract_with_public_external_functions_and_events(self, tmp_path):
        """Reproduces the real Quantitativo Executor.sol shape."""
        content = (
            "contract Executor {\n"
            "    event Executed(bytes32 indexed id, uint256 profit);\n"
            "\n"
            "    function execute(address target, bytes calldata data) external payable onlyOwner {\n"
            "        target.call(data);\n"
            "    }\n"
            "\n"
            "    function _internalOnly() private {\n"
            "        return;\n"
            "    }\n"
            "}\n"
        )
        p = _write(tmp_path, "src/Executor.sol", content)
        result = self.adapter.scan_file(p, "src/Executor.sol")
        assert result["exports"] == ["Executed", "Executor", "execute"]

    def test_multiline_signature_visibility_checked_across_lines(self, tmp_path):
        """Reproduces the real HZ02.sol shape: visibility comes after the
        parameter list, which itself wraps across multiple lines."""
        content = (
            "contract HZ02 {\n"
            "    function mintFromBatch(\n"
            "        address to,\n"
            "        uint256 amount\n"
            "    ) external onlyRole(MINTER_ROLE) {\n"
            "        _mint(to, amount);\n"
            "    }\n"
            "\n"
            "    function _internalMint(\n"
            "        address to\n"
            "    ) internal {\n"
            "        return;\n"
            "    }\n"
            "}\n"
        )
        p = _write(tmp_path, "contracts/HZ02.sol", content)
        result = self.adapter.scan_file(p, "contracts/HZ02.sol")
        assert result["exports"] == ["HZ02", "mintFromBatch"]

    def test_should_skip_vendored_and_build_dirs(self, tmp_path):
        assert self.adapter.should_skip("lib/forge-std/src/Test.sol", tmp_path) is True
        assert self.adapter.should_skip("out/Executor.sol", tmp_path) is True
        assert self.adapter.should_skip("src/Executor.sol", tmp_path) is False

    def test_exclude_suffixes_skip_tests_and_scripts(self, tmp_path):
        assert self.adapter.exclude_suffixes == (".t.sol", ".s.sol")


class TestDartAdapter:
    def setup_method(self):
        self.adapter = DartAdapter()

    def test_class_and_methods(self, tmp_path):
        """Reproduces the real Rodax ApiClient shape: return-type-prefixed
        methods, a private field, and a factory constructor."""
        content = (
            "class ApiClient {\n"
            "  static final ApiClient _instance = ApiClient._internal();\n"
            "  factory ApiClient() => _instance;\n"
            "\n"
            "  String? _accessToken;\n"
            "\n"
            "  void setAccessToken(String? token) {\n"
            "    _accessToken = token;\n"
            "  }\n"
            "\n"
            "  Future<Response<T>> get<T>(String path) {\n"
            "    return _dio.get<T>(path);\n"
            "  }\n"
            "}\n"
        )
        p = _write(tmp_path, "core/network/api_client.dart", content)
        result = self.adapter.scan_file(p, "core/network/api_client.dart")
        assert result["exports"] == ["ApiClient", "setAccessToken"]
        assert result["layer"] == "core"

    def test_private_state_class_and_members_excluded(self, tmp_path):
        """Reproduces the extremely common StatefulWidget companion-class
        pattern: `class _FooState extends State<Foo>` is private by
        convention (leading underscore), same as its private members."""
        content = (
            "class RodaxButton extends StatefulWidget {\n"
            "  const RodaxButton({super.key});\n"
            "}\n"
            "\n"
            "class _RodaxButtonState extends State<RodaxButton> {\n"
            "  void _privateHelper() {}\n"
            "\n"
            "  void build() {}\n"
            "}\n"
        )
        p = _write(tmp_path, "design_system/atoms/buttons/rodax_button.dart", content)
        result = self.adapter.scan_file(p, "design_system/atoms/buttons/rodax_button.dart")
        assert "RodaxButton" in result["exports"]
        assert "_RodaxButtonState" not in result["exports"]
        assert "_privateHelper" not in result["exports"]
        assert "build" not in result["exports"]

    def test_nested_indentation_inside_method_body_not_matched_as_member(self, tmp_path):
        """Guards the `(?=\\S)` fix: an `if (...)` deep inside a method body
        must not be picked up as if it were a direct class member."""
        content = (
            "class Widget {\n"
            "  void run() {\n"
            "    if (ready()) {\n"
            "      doThing();\n"
            "    }\n"
            "  }\n"
            "}\n"
        )
        p = _write(tmp_path, "widget.dart", content)
        result = self.adapter.scan_file(p, "widget.dart")
        assert result["exports"] == ["Widget", "run"]

    def test_export_barrel_recorded_as_reexports(self, tmp_path):
        content = "export 'tokens/colors.dart';\nexport 'theme/app_theme.dart';\n"
        p = _write(tmp_path, "design_system/design_system.dart", content)
        result = self.adapter.scan_file(p, "design_system/design_system.dart")
        assert result["reExportsFrom"] == ["theme/app_theme.dart", "tokens/colors.dart"]

    def test_exclude_suffixes_skip_codegen_and_tests(self, tmp_path):
        assert self.adapter.exclude_suffixes == (".g.dart", ".freezed.dart", "_test.dart")
