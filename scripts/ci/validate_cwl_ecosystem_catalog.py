#!/usr/bin/env python3
"""Validate the bounded CWL service capability and relationship catalogue."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from cwl_catalog_contract import (
    CATALOG_FIELDS,
    MANIFEST_REFERENCE_FIELDS,
    MATURITY_LEVELS,
    CatalogValidationError,
    require_array,
    require_closed_object,
    require_enum,
    require_identifier,
    require_manifest_path,
    require_semver,
)
from cwl_catalog_io import load_json, resolve_manifest_path, validate_bounded_value
from cwl_catalog_relationship import validate_relationship
from cwl_catalog_service import validate_service


def _load_services(catalog: dict[str, Any], catalog_path: Path) -> dict[str, dict[str, Any]]:
    """Load referenced service manifests and enforce unique identity and repository ownership."""

    references = require_array(catalog["service_manifests"], "service_manifests")
    if not references:
        raise CatalogValidationError("service_manifests must contain at least one manifest")
    services: dict[str, dict[str, Any]] = {}
    repositories: set[str] = set()
    authority_owners: dict[str, str] = {}
    manifest_paths: set[str] = set()
    service_ids: set[str] = set()
    normalized_references: list[tuple[str, str]] = []
    for index, raw_reference in enumerate(references):
        path = f"service_manifests[{index}]"
        reference = require_closed_object(raw_reference, path, MANIFEST_REFERENCE_FIELDS)
        expected_id = require_identifier(reference["service_id"], f"{path}.service_id")
        relative = require_manifest_path(reference["manifest_path"], f"{path}.manifest_path")
        if expected_id in service_ids:
            raise CatalogValidationError(f"duplicate service_id: {expected_id}")
        if relative in manifest_paths:
            raise CatalogValidationError(f"duplicate service manifest path: {relative}")
        service_ids.add(expected_id)
        manifest_paths.add(relative)
        normalized_references.append((expected_id, relative))
    for index, (expected_id, relative) in enumerate(normalized_references):
        path = f"service_manifests[{index}]"
        manifest_path = resolve_manifest_path(catalog_path, relative)
        raw_service = load_json(manifest_path)
        validate_bounded_value(raw_service)
        service = validate_service(raw_service, f"service[{expected_id}]")
        actual_id = str(service["service_id"])
        if actual_id != expected_id:
            raise CatalogValidationError(f"{path}.service_id does not match the referenced manifest")
        repository = str(service["repository"])
        if repository in repositories:
            raise CatalogValidationError(f"duplicate repository: {repository}")
        for authority_domain in service["authority_domains"]:
            previous_owner = authority_owners.get(authority_domain)
            if previous_owner is not None:
                raise CatalogValidationError(
                    "duplicate authority domain: "
                    f"{authority_domain} belongs to {previous_owner} and {repository}"
                )
            authority_owners[authority_domain] = repository
        services[actual_id] = service
        repositories.add(repository)
    for service_id, service in services.items():
        for consumer in service["consumer_repositories"]:
            if consumer not in repositories:
                raise CatalogValidationError(f"service[{service_id}] references an uncatalogued consumer repository")
    return services


def validate_catalog(path: Path) -> None:
    """Validate the catalogue at *path* or raise :class:`CatalogValidationError`."""

    raw_catalog = load_json(path)
    validate_bounded_value(raw_catalog)
    catalog = require_closed_object(raw_catalog, "catalogue", CATALOG_FIELDS)
    if catalog["schema_version"] != "1.0.0":
        raise CatalogValidationError("catalogue.schema_version must be 1.0.0")
    require_identifier(catalog["catalog_id"], "catalogue.catalog_id")
    require_semver(catalog["catalog_version"], "catalogue.catalog_version")
    require_enum(catalog["maturity"], "catalogue.maturity", MATURITY_LEVELS)
    services = _load_services(catalog, path)
    relationships = require_array(catalog["relationships"], "relationships")
    relationship_ids: set[str] = set()
    for index, raw_relationship in enumerate(relationships):
        relation = validate_relationship(raw_relationship, index, services)
        relationship_id = str(relation["relationship_id"])
        if relationship_id in relationship_ids:
            raise CatalogValidationError(f"duplicate relationship_id: {relationship_id}")
        relationship_ids.add(relationship_id)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the catalogue validator and return a stable process status code."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("usage: validate_cwl_ecosystem_catalog.py CATALOG.json", file=sys.stderr)
        return 2
    path = Path(arguments[0])
    try:
        validate_catalog(path)
    except CatalogValidationError as error:
        print(f"CWL ecosystem catalogue validation failed: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"CWL ecosystem catalogue could not read catalogue: {error}", file=sys.stderr)
        return 2
    print(f"CWL ecosystem catalogue validated: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
