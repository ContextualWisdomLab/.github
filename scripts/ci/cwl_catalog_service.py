"""Service-capability semantic validation for the CWL catalogue."""

from __future__ import annotations

from typing import Any

if __package__:  # pragma: no cover - exercised by the module CLI subprocess
    from .cwl_catalog_contract import (
        ARTIFACT_FIELDS,
        ARTIFACT_KINDS,
        CONTRACT_DIRECTIONS,
        CONTRACT_FIELDS,
        CONTRACT_KINDS,
        DATABASE_OWNERSHIP_FIELDS,
        DATA_CLASSIFICATIONS,
        INTEGRATION_MODES,
        MATURITY_LEVELS,
        NEXT_ACTION_FIELDS,
        SERVICE_FIELDS,
        CatalogValidationError,
        require_array,
        require_boolean,
        require_closed_object,
        require_enum,
        require_identifier,
        require_immutable_reference,
        require_nonempty_string,
        require_repository,
        require_semver,
        require_unique_strings,
    )
else:
    from cwl_catalog_contract import (
        ARTIFACT_FIELDS,
        ARTIFACT_KINDS,
        CONTRACT_DIRECTIONS,
        CONTRACT_FIELDS,
        CONTRACT_KINDS,
        DATABASE_OWNERSHIP_FIELDS,
        DATA_CLASSIFICATIONS,
        INTEGRATION_MODES,
        MATURITY_LEVELS,
        NEXT_ACTION_FIELDS,
        SERVICE_FIELDS,
        CatalogValidationError,
        require_array,
        require_boolean,
        require_closed_object,
        require_enum,
        require_identifier,
        require_immutable_reference,
        require_nonempty_string,
        require_repository,
        require_semver,
        require_unique_strings,
    )


def validate_next_actions(value: object, path: str) -> None:
    """Require actionable success, rejection, timeout, duplicate, and rollback text."""

    actions = require_closed_object(value, path, NEXT_ACTION_FIELDS)
    for field in NEXT_ACTION_FIELDS:
        require_nonempty_string(actions[field], f"{path}.{field}")


def validate_contract(value: object, path: str) -> dict[str, Any]:
    """Validate one versioned provider contract reference."""

    contract = require_closed_object(value, path, CONTRACT_FIELDS)
    require_identifier(contract["contract_id"], f"{path}.contract_id")
    require_enum(contract["contract_kind"], f"{path}.contract_kind", CONTRACT_KINDS)
    require_semver(contract["contract_version"], f"{path}.contract_version")
    require_immutable_reference(contract["immutable_reference"], f"{path}.immutable_reference")
    require_enum(contract["direction"], f"{path}.direction", CONTRACT_DIRECTIONS)
    require_enum(contract["maturity"], f"{path}.maturity", MATURITY_LEVELS)
    return contract


def validate_database_ownership(value: object, path: str, service_id: str) -> None:
    """Validate authoritative state ownership and the no-cross-service-SQL rule."""

    ownership = require_closed_object(value, path, DATABASE_OWNERSHIP_FIELDS)
    owns_state = require_boolean(ownership["owns_durable_state"], f"{path}.owns_durable_state")
    if require_identifier(ownership["authoritative_service_id"], f"{path}.authoritative_service_id") != service_id:
        raise CatalogValidationError(f"{path}.authoritative_service_id must equal service_id")
    objects = require_unique_strings(
        ownership["owned_database_objects"],
        f"{path}.owned_database_objects",
        validator=require_identifier,
    )
    if not owns_state and objects:
        raise CatalogValidationError(f"{path} cannot declare database objects without durable state")
    if require_boolean(ownership["direct_cross_repository_sql"], f"{path}.direct_cross_repository_sql"):
        raise CatalogValidationError("direct cross-repository SQL is forbidden")


def validate_artifacts(value: object, path: str) -> None:
    """Validate unique, immutable released-artifact identities."""

    artifacts = require_array(value, path)
    artifact_ids: set[str] = set()
    for index, raw_artifact in enumerate(artifacts):
        artifact_path = f"{path}[{index}]"
        artifact = require_closed_object(raw_artifact, artifact_path, ARTIFACT_FIELDS)
        artifact_id = require_identifier(artifact["artifact_id"], f"{artifact_path}.artifact_id")
        if artifact_id in artifact_ids:
            raise CatalogValidationError(f"{path} contains duplicate artifact_id")
        artifact_ids.add(artifact_id)
        require_enum(artifact["artifact_kind"], f"{artifact_path}.artifact_kind", ARTIFACT_KINDS)
        require_semver(artifact["artifact_version"], f"{artifact_path}.artifact_version")
        require_immutable_reference(artifact["immutable_reference"], f"{artifact_path}.immutable_reference")
        require_enum(artifact["maturity"], f"{artifact_path}.maturity", MATURITY_LEVELS)


def validate_service(value: object, path: str) -> dict[str, Any]:
    """Validate one repository-owned service capability manifest."""

    service = require_closed_object(value, path, SERVICE_FIELDS)
    if service["schema_version"] != "1.0.0":
        raise CatalogValidationError(f"{path}.schema_version must be 1.0.0")
    service_id = require_identifier(service["service_id"], f"{path}.service_id")
    repository = require_repository(service["repository"], f"{path}.repository")
    require_nonempty_string(service["product_boundary"], f"{path}.product_boundary")
    require_enum(service["integration_mode"], f"{path}.integration_mode", INTEGRATION_MODES)
    require_enum(service["maturity"], f"{path}.maturity", MATURITY_LEVELS)
    require_unique_strings(service["authority_domains"], f"{path}.authority_domains", minimum=1, validator=require_identifier)
    consumers = require_unique_strings(service["consumer_repositories"], f"{path}.consumer_repositories", validator=require_repository)
    if repository in consumers:
        raise CatalogValidationError(f"{path} must not list its own repository as a consumer")
    contracts = require_array(service["contracts"], f"{path}.contracts")
    if not contracts:
        raise CatalogValidationError(f"{path}.contracts must contain at least one contract")
    contract_ids: set[str] = set()
    for index, raw_contract in enumerate(contracts):
        contract = validate_contract(raw_contract, f"{path}.contracts[{index}]")
        contract_id = str(contract["contract_id"])
        if contract_id in contract_ids:
            raise CatalogValidationError(f"{path}.contracts contains duplicate contract_id")
        contract_ids.add(contract_id)
    validate_database_ownership(service["database_ownership"], f"{path}.database_ownership", service_id)
    require_unique_strings(
        service["data_classifications"],
        f"{path}.data_classifications",
        minimum=1,
        validator=lambda item, item_path: require_enum(item, item_path, DATA_CLASSIFICATIONS),
    )
    validate_artifacts(service["released_artifacts"], f"{path}.released_artifacts")
    validate_next_actions(service["next_actions"], f"{path}.next_actions")
    return service
