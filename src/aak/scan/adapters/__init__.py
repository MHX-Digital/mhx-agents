from .python import PythonAdapter
from .typescript import TypeScriptAdapter

ADAPTERS = {
    "typescript": TypeScriptAdapter,
    "python": PythonAdapter,
}
