from .python import PythonAdapter
from .typescript import TypeScriptAdapter
from .rust import RustAdapter
from .solidity import SolidityAdapter
from .dart import DartAdapter

ADAPTERS = {
    "typescript": TypeScriptAdapter,
    "python": PythonAdapter,
    "rust": RustAdapter,
    "solidity": SolidityAdapter,
    "dart": DartAdapter,
}
