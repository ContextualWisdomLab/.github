"""Shared test helpers for CWL catalogue contracts."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / "scripts/ci"
if str(CI) not in sys.path:
    sys.path.insert(0, str(CI))

import validate_cwl_ecosystem_catalog as validator  # noqa: E402

CATALOG = ROOT / "schemas/examples/cwl-ecosystem-catalog-v1.example.json"
SERVICES = CATALOG.parent / "services"


def load_catalog() -> dict[str, Any]:
    """Return a deep copy of the positive catalogue."""

    return copy.deepcopy(json.loads(CATALOG.read_text(encoding="utf-8")))


def load_service(service_id: str = "identity_federation") -> dict[str, Any]:
    """Return a deep copy of one positive service manifest."""

    return copy.deepcopy(json.loads((SERVICES / f"{service_id}.json").read_text(encoding="utf-8")))


def write_catalog_tree(tmp_path: Path, catalog: dict[str, Any] | None = None) -> Path:
    """Copy positive manifests and write a mutable catalogue fixture."""

    service_dir = tmp_path / "services"
    service_dir.mkdir(parents=True)
    for source in SERVICES.glob("*.json"):
        (service_dir / source.name).write_bytes(source.read_bytes())
    target = tmp_path / "catalog.json"
    target.write_text(json.dumps(catalog or load_catalog(), ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return target


def write_service(tmp_path: Path, service_id: str, value: dict[str, Any]) -> Path:
    """Replace one copied service manifest and return the catalogue path."""

    catalog_path = write_catalog_tree(tmp_path)
    (tmp_path / "services" / f"{service_id}.json").write_text(
        json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    return catalog_path
