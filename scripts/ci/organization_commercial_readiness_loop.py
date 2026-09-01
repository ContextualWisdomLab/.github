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
    """Load one trusted sibling module under a stable private module name."""
    path = _MODULE_DIRECTORY / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
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
_core.DDD_CONTRACT_CAPABILITIES = _ddd.DDD_CONTRACT_CAPABILITIES

if __name__ == "__main__":
    raise SystemExit(_core.main())

sys.modules[__name__] = _core
