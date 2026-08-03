"""Loads custom_components/renac_wallbox/<name>.py as a real module with
working relative imports (`from .const import ...`), without executing
the package's __init__.py — which pulls in `homeassistant`, a dependency
these lightweight tests intentionally don't require.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

COMPONENT_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "renac_wallbox"
_PKG_NAME = "renac_wallbox_under_test"

if _PKG_NAME not in sys.modules:
    pkg = types.ModuleType(_PKG_NAME)
    pkg.__path__ = [str(COMPONENT_DIR)]
    sys.modules[_PKG_NAME] = pkg


def load_component(module_name: str) -> types.ModuleType:
    full_name = f"{_PKG_NAME}.{module_name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(
        full_name, COMPONENT_DIR / f"{module_name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = _PKG_NAME
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module
