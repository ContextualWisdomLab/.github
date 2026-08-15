"""Expose the bounded catalogue helper for direct pytest node collection."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_HELPER_NAME = "catalogue_test_helpers"
_HELPER_PATH = Path(__file__).with_name(f"{_HELPER_NAME}.py")

if _HELPER_NAME not in sys.modules:
    _SPEC = importlib.util.spec_from_file_location(_HELPER_NAME, _HELPER_PATH)
    if _SPEC is None or _SPEC.loader is None:
        raise RuntimeError("catalogue test helper could not be loaded")
    _MODULE = importlib.util.module_from_spec(_SPEC)
    sys.modules[_HELPER_NAME] = _MODULE
    _SPEC.loader.exec_module(_MODULE)
