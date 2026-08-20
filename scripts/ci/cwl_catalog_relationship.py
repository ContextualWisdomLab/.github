"""Provider-consumer relationship validation for the CWL catalogue."""

from __future__ import annotations

from typing import Any

if __package__:  # pragma: no cover - exercised by the module CLI subprocess
    from .cwl_catalog_contract import (
        CONTRACT_KINDS,
        CREDENTIAL_FLOWS,
        DATA_CLASSIFICATIONS,
        DATA_FLOW_CLASSES,
        EVIDENCE_CLASSES,
        MATURITY_LEVELS,
        MATURITY_RANK,
        RELATIONSHIP_FIELDS,
        CatalogValidationError,
        require_boolean,
        require_closed_object,
        require_enum,
        require_identifier,
        require_immutable_reference,
        require_semver,
    )
    from .cwl_catalog_service import validate_next_actions
else:
    from cwl_catalog_contract import (
        CONTRACT_KINDS,
        CREDENTIAL_FLOWS,
        DATA_CLASSIFICATIONS,
        DATA_FLOW_CLASSES,
        EVIDENCE_CLASSES,
        MATURITY_LEVELS,
        MATURITY_RANK,
        RELATIONSHIP_FIELDS,
        CatalogValidationError,
        require_boolean,
        require_closed_object,
        require_enum,
        require_identifier,
        require_immutable_reference,
        require_semver,
    )
    from cwl_catalog_service import validate_next_actions


def validate_relationship(value: object, index: int, services: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Validate one purpose-bound provider-consumer relationship edge."""

    path = f"relationships[{index}]"
    relation = require_closed_object(value, path, RELATIONSHIP_FIELDS)
    require_identifier(relation["relationship_id"], f"{path}.relationship_id")
    provider = require_identifier(relation["provider_service_id"], f"{path}.provider_service_id")
    consumer = require_identifier(relation["consumer_service_id"], f"{path}.consumer_service_id")
    owner = require_identifier(relation["authoritative_data_owner_service_id"], f"{path}.authoritative_data_owner_service_id")
    if provider not in services:
        raise CatalogValidationError(f"{path} references unknown provider service")
    if consumer not in services:
        raise CatalogValidationError(f"{path} references unknown consumer service")
    if owner not in services:
        raise CatalogValidationError(f"{path} references unknown authoritative data owner")
    if provider == consumer:
        raise CatalogValidationError(f"{path} creates a forbidden self-edge")
    kind = require_enum(relation["contract_kind"], f"{path}.contract_kind", CONTRACT_KINDS)
    require_semver(relation["contract_version"], f"{path}.contract_version")
    require_immutable_reference(relation["immutable_reference"], f"{path}.immutable_reference")
    require_identifier(relation["purpose_code"], f"{path}.purpose_code")
    classification = require_enum(relation["data_classification"], f"{path}.data_classification", DATA_CLASSIFICATIONS)
    flow = require_enum(relation["data_flow_class"], f"{path}.data_flow_class", DATA_FLOW_CLASSES)
    evidence = require_enum(relation["evidence_class"], f"{path}.evidence_class", EVIDENCE_CLASSES)
    maturity = require_enum(relation["maturity"], f"{path}.maturity", MATURITY_LEVELS)
    require_enum(relation["credential_flow"], f"{path}.credential_flow", CREDENTIAL_FLOWS)
    if require_boolean(relation["direct_cross_repository_sql"], f"{path}.direct_cross_repository_sql"):
        raise CatalogValidationError("direct cross-repository SQL is forbidden")
    if require_boolean(relation["credential_copying"], f"{path}.credential_copying"):
        raise CatalogValidationError("credential copying is forbidden")
    if require_boolean(relation["raw_pii_broadcast"], f"{path}.raw_pii_broadcast"):
        raise CatalogValidationError("raw PII broadcast is forbidden")
    may_update = require_boolean(relation["may_update_authoritative_fact"], f"{path}.may_update_authoritative_fact")
    validate_next_actions(relation["next_actions"], f"{path}.next_actions")

    if evidence == "inferred_relationship" and may_update:
        raise CatalogValidationError("an inferred relationship may not update an authoritative fact")
    if flow == "no_business_data" and classification != "no_business_data":
        raise CatalogValidationError("no_business_data flow must use no_business_data classification")
    if kind == "build_control" and (flow != "no_business_data" or classification != "no_business_data" or may_update):
        raise CatalogValidationError("build_control relationships may carry no business data and no authoritative writes")
    if classification in {"restricted_identity", "restricted_hr"} and flow in {"schema_contract", "no_business_data"}:
        raise CatalogValidationError("restricted data requires a purpose-bound, reference-only, aggregate, or opt-in flow")
    if may_update and owner != consumer:
        raise CatalogValidationError(f"{path} may update authoritative facts only at the authoritative consumer")
    maximum = min(MATURITY_RANK[str(services[provider]["maturity"])], MATURITY_RANK[str(services[consumer]["maturity"])])
    if MATURITY_RANK[maturity] > maximum:
        raise CatalogValidationError(f"{path}.maturity exceeds endpoint maturity")
    return relation
