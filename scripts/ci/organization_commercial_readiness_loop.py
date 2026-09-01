#!/usr/bin/env python3
"""Compatibility entrypoint for the organization commercial-readiness core."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_MODULE_DIRECTORY = Path(__file__).resolve().parent
_CORE_MODULE_NAME = "_cwl_organization_commercial_readiness_core"
_DDD_MODULE_NAME = "_cwl_organization_commercial_readiness_ddd_contract"


def _load_sibling(module_name: str, filename: str) -> ModuleType:
    """Load one sibling module under a stable private module name."""
    path = _MODULE_DIRECTORY / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_core = _load_sibling(
    _CORE_MODULE_NAME, "organization_commercial_readiness_core.py"
)
_ddd = _load_sibling(
    _DDD_MODULE_NAME, "organization_commercial_readiness_ddd_contract.py"
)

_core.has_domain_driven_development_contract = (
    _ddd.has_domain_driven_development_contract
)
_core.DDD_CONTRACT_TERMS = _ddd.DDD_CONTRACT_TERMS

for _export_name in dir(_core):
    if not _export_name.startswith("__"):
        globals()[_export_name] = getattr(_core, _export_name)

DDD_CONTRACT_CAPABILITIES = _ddd.DDD_CONTRACT_CAPABILITIES
DDD_CONTRACT_TERMS = _ddd.DDD_CONTRACT_TERMS
has_domain_driven_development_contract = (
    _ddd.has_domain_driven_development_contract
)


if __name__ == "__main__":
    raise SystemExit(_core.main())
