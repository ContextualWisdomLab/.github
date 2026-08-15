"""RED contracts for the CWL ecosystem capability catalogue."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/ci/validate_cwl_ecosystem_catalog.py"
SERVICE_SCHEMA = ROOT / "schemas/cwl-service-capability-v1.schema.json"
CATALOG_SCHEMA = ROOT / "schemas/cwl-ecosystem-catalog-v1.schema.json"
CATALOG = ROOT / "schemas/examples/cwl-ecosystem-catalog-v1.example.json"


def _load_validator() -> object:
    """Load the production validator from its final repository path."""

    spec = importlib.util.spec_from_file_location("cwl_catalog", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_catalogue_contract_is_executable_and_closed() -> None:
    """Schemas, catalogue, and production validation must agree exactly."""

    validator = _load_validator()
    service_schema = json.loads(SERVICE_SCHEMA.read_text(encoding="utf-8"))
    catalog_schema = json.loads(CATALOG_SCHEMA.read_text(encoding="utf-8"))
    assert service_schema["additionalProperties"] is False
    assert catalog_schema["additionalProperties"] is False
    assert set(service_schema["required"]) == set(validator.SERVICE_FIELDS)
    assert set(catalog_schema["required"]) == set(validator.CATALOG_FIELDS)
    validator.validate_catalog(CATALOG)


def test_catalogue_rejects_direct_sql_and_raw_pii(tmp_path: Path) -> None:
    """Unsafe cross-repository data paths must fail closed."""

    validator = _load_validator()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    relationship = catalog["relationships"][0]
    relationship["direct_cross_repository_sql"] = True
    relationship["raw_pii_broadcast"] = True
    candidate = tmp_path / "catalog.json"
    candidate.write_text(json.dumps(catalog), encoding="utf-8")
    try:
        validator.validate_catalog(candidate)
    except validator.CatalogValidationError as error:
        assert "direct cross-repository SQL" in str(error)
    else:
        raise AssertionError("unsafe catalogue relationship was accepted")
