"""Primitive contracts and controlled vocabularies for the CWL catalogue."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 20
MAX_COLLECTION_ITEMS = 4096
MAX_STRING_LENGTH = 8192

SERVICE_FIELDS = (
    "schema_version", "service_id", "repository", "product_boundary",
    "integration_mode", "maturity", "authority_domains",
    "consumer_repositories", "contracts", "database_ownership",
    "data_classifications", "released_artifacts", "next_actions",
)
CATALOG_FIELDS = (
    "schema_version", "catalog_id", "catalog_version", "maturity",
    "service_manifests", "relationships",
)
MANIFEST_REFERENCE_FIELDS = ("service_id", "manifest_path")
RELATIONSHIP_FIELDS = (
    "relationship_id", "provider_service_id", "consumer_service_id",
    "authoritative_data_owner_service_id", "contract_kind",
    "contract_version", "immutable_reference", "purpose_code",
    "data_classification", "data_flow_class", "evidence_class", "maturity",
    "credential_flow", "direct_cross_repository_sql", "credential_copying",
    "raw_pii_broadcast", "may_update_authoritative_fact", "next_actions",
)
CONTRACT_FIELDS = (
    "contract_id", "contract_kind", "contract_version", "immutable_reference",
    "direction", "maturity",
)
DATABASE_OWNERSHIP_FIELDS = (
    "owns_durable_state", "authoritative_service_id",
    "owned_database_objects", "direct_cross_repository_sql",
)
ARTIFACT_FIELDS = (
    "artifact_id", "artifact_kind", "artifact_version", "immutable_reference",
    "maturity",
)
NEXT_ACTION_FIELDS = ("success", "rejection", "timeout", "duplicate", "rollback")

INTEGRATION_MODES = (
    "in_process_package", "independent_service", "offline_scientific_worker",
    "build_operations_tool",
)
DATA_FLOW_CLASSES = (
    "reference_only", "purpose_bound_projection", "aggregate_artifact",
    "schema_contract", "no_business_data", "explicit_opt_in_projection",
)
MATURITY_LEVELS = (
    "planned", "accepted_architecture", "active_pr",
    "implemented_on_protected_main", "released", "deprecated", "superseded",
)
CONTRACT_KINDS = (
    "openapi", "asyncapi_event", "package", "artifact_handoff",
    "scientific_job", "build_control", "oauth_oidc", "database_migration",
    "schema_contract",
)
CONTRACT_DIRECTIONS = (
    "provider_to_consumer", "consumer_to_provider", "bidirectional",
    "offline_import",
)
DATA_CLASSIFICATIONS = (
    "public", "internal", "confidential", "restricted_identity",
    "restricted_hr", "security_metadata", "no_business_data",
)
EVIDENCE_CLASSES = (
    "authoritative_fact", "authoritative_reference", "derived_artifact",
    "inferred_relationship", "control_evidence", "no_business_data",
)
CREDENTIAL_FLOWS = ("none", "workload_identity", "delegated_user_token")
ARTIFACT_KINDS = (
    "python_wheel", "npm_package", "oci_image", "json_schema",
    "openapi_document", "asyncapi_document", "sbom", "data_artifact",
)
MATURITY_RANK = {
    "planned": 0, "accepted_architecture": 1, "active_pr": 2,
    "implemented_on_protected_main": 3, "released": 4,
    "deprecated": 4, "superseded": 4,
}

_TWO_WORD_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
_REPOSITORY = re.compile(r"^ContextualWisdomLab/[A-Za-z0-9_.-]+$")
_SEMVER = re.compile(r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")
_IMMUTABLE_REFERENCE = re.compile(
    r"(?:@[1-9][0-9]*\.[0-9]+\.[0-9]+(?:$|[#:/])|"
    r"(?:@|/commit/)[0-9a-f]{40}(?:$|[#:/])|"
    r"@sha256:[0-9a-f]{64}(?:$|[#:/]))"
)
_MANIFEST_PATH = re.compile(r"^services/[a-z][a-z0-9]*(?:_[a-z0-9]+)+\.json$")


class CatalogValidationError(ValueError):
    """Report one bounded, operator-readable catalogue contract violation."""


def require_object(value: object, path: str) -> dict[str, Any]:
    """Return *value* as a JSON object or reject the named field."""

    if not isinstance(value, dict):
        raise CatalogValidationError(f"{path} must be an object")
    return value


def require_array(value: object, path: str) -> list[Any]:
    """Return *value* as a JSON array or reject the named field."""

    if not isinstance(value, list):
        raise CatalogValidationError(f"{path} must be an array")
    return value


def require_closed_object(value: object, path: str, fields: Iterable[str]) -> dict[str, Any]:
    """Require one object to contain exactly the declared *fields*."""

    obj = require_object(value, path)
    expected, actual = set(fields), set(obj)
    unknown, missing = sorted(actual - expected), sorted(expected - actual)
    if unknown:
        raise CatalogValidationError(f"{path} has unknown properties: {unknown}")
    if missing:
        raise CatalogValidationError(f"{path} has missing properties: {missing}")
    return obj


def require_nonempty_string(value: object, path: str) -> str:
    """Return a nonempty string or reject the named field."""

    if not isinstance(value, str) or not value.strip():
        raise CatalogValidationError(f"{path} must be a non-empty string")
    return value


def require_identifier(value: object, path: str) -> str:
    """Require a descriptive two-or-more-word lowercase snake-case identifier."""

    text = require_nonempty_string(value, path)
    if _TWO_WORD_SNAKE_CASE.fullmatch(text) is None:
        raise CatalogValidationError(f"{path} must use two-word lowercase snake_case")
    return text


def require_repository(value: object, path: str) -> str:
    """Require one canonical ContextualWisdomLab repository name."""

    text = require_nonempty_string(value, path)
    if _REPOSITORY.fullmatch(text) is None:
        raise CatalogValidationError(f"{path} must be a canonical CWL repository")
    return text


def require_semver(value: object, path: str) -> str:
    """Require an explicit nonzero-major semantic version."""

    text = require_nonempty_string(value, path)
    if _SEMVER.fullmatch(text) is None:
        raise CatalogValidationError(f"{path} must be a semantic version")
    return text


def require_enum(value: object, path: str, allowed: Sequence[str]) -> str:
    """Require one string from a finite controlled vocabulary."""

    text = require_nonempty_string(value, path)
    if text not in allowed:
        raise CatalogValidationError(f"{path} is outside the controlled vocabulary")
    return text


def require_boolean(value: object, path: str) -> bool:
    """Require a JSON boolean without accepting integers."""

    if type(value) is not bool:
        raise CatalogValidationError(f"{path} must be a boolean")
    return value


def require_unique_strings(
    value: object,
    path: str,
    *,
    minimum: int = 0,
    validator: Any | None = None,
) -> list[str]:
    """Require a bounded array of unique strings using an optional validator."""

    items = require_array(value, path)
    if len(items) < minimum:
        raise CatalogValidationError(f"{path} must contain at least {minimum} item(s)")
    strings = [
        validator(item, f"{path}[{index}]") if validator else require_nonempty_string(item, f"{path}[{index}]")
        for index, item in enumerate(items)
    ]
    if len(strings) != len(set(strings)):
        raise CatalogValidationError(f"{path} contains duplicate values")
    return strings


def require_immutable_reference(value: object, path: str) -> str:
    """Require a semantic-version, commit-SHA, or digest-pinned reference."""

    text = require_nonempty_string(value, path)
    if _IMMUTABLE_REFERENCE.search(text) is None:
        raise CatalogValidationError(f"{path} must contain an immutable version, commit, or digest")
    return text


def require_manifest_path(value: object, path: str) -> str:
    """Require one normalized service-manifest path below `services/`."""

    text = require_nonempty_string(value, path)
    if _MANIFEST_PATH.fullmatch(text) is None:
        raise CatalogValidationError(f"{path} must be a normalized services/*.json path")
    return text
