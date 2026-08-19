"""Service-manifest semantic tests for the CWL catalogue."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from catalogue_test_helpers import (
    load_catalog,
    load_service,
    validator,
    write_catalog_tree,
    write_service,
)
from cwl_catalog_contract import CatalogValidationError
from cwl_catalog_service import (
    validate_artifacts,
    validate_contract,
    validate_database_ownership,
    validate_next_actions,
    validate_service,
)

EXPECTED_REPOSITORIES = {
    "ContextualWisdomLab/.github",
    "ContextualWisdomLab/naruon",
    "ContextualWisdomLab/Orgmetra",
    "ContextualWisdomLab/keyverse",
    "ContextualWisdomLab/contextual-orchestrator",
    "ContextualWisdomLab/psychometrics-commons",
    "ContextualWisdomLab/fast-mlsirm",
    "ContextualWisdomLab/TEPP",
    "ContextualWisdomLab/semantic-data-portal",
    "ContextualWisdomLab/OriginWeave",
    "ContextualWisdomLab/newsdom-api",
    "ContextualWisdomLab/RankWeave",
    "ContextualWisdomLab/ThreadWeave",
    "ContextualWisdomLab/EgressWeave",
    "ContextualWisdomLab/LineageWeave",
    "ContextualWisdomLab/inkspan",
    "ContextualWisdomLab/clearfolio",
    "ContextualWisdomLab/mhtml-etl-gateway",
    "ContextualWisdomLab/mightyETL",
    "ContextualWisdomLab/pg-erd-cloud",
    "ContextualWisdomLab/EmbedRelay",
    "ContextualWisdomLab/appguardrail",
    "ContextualWisdomLab/life-os",
    "ContextualWisdomLab/bandscope",
}


def test_initial_catalogue_covers_exact_high_leverage_repository_set(
    tmp_path: Path,
) -> None:
    """The reviewed v1 catalogue must cover the complete initial repository set."""

    path = write_catalog_tree(tmp_path)
    validator.validate_catalog(path)
    repositories = {
        load_service(reference["service_id"])["repository"]
        for reference in load_catalog()["service_manifests"]
    }
    assert repositories == EXPECTED_REPOSITORIES


def test_service_contract_fields_and_nested_shapes_are_strict(tmp_path: Path) -> None:
    """Service manifests must use exact fields, controlled values, and unique contracts."""

    service = load_service()
    mutations = [
        (lambda s: s.__setitem__("extra", True), "unknown properties"),
        (lambda s: s.pop("repository"), "missing properties"),
        (lambda s: s.__setitem__("schema_version", "2.0.0"), "schema_version"),
        (lambda s: s.__setitem__("service_id", "single"), "service_id"),
        (lambda s: s.__setitem__("repository", "other/repo"), "repository"),
        (lambda s: s.__setitem__("product_boundary", ""), "product_boundary"),
        (lambda s: s.__setitem__("integration_mode", "network"), "controlled"),
        (lambda s: s.__setitem__("maturity", "complete"), "controlled"),
        (lambda s: s.__setitem__("authority_domains", []), "at least"),
        (lambda s: s.__setitem__("authority_domains", ["single"]), "snake_case"),
        (lambda s: s.__setitem__("consumer_repositories", "bad"), "array"),
        (
            lambda s: s.__setitem__("consumer_repositories", [s["repository"]]),
            "own repository",
        ),
        (lambda s: s.__setitem__("contracts", []), "at least one"),
        (
            lambda s: s.__setitem__("contracts", ["bad"]),
            r"contracts\[0\] must be an object",
        ),
        (
            lambda s: s.__setitem__("database_ownership", "bad"),
            "database_ownership must be an object",
        ),
        (lambda s: s.__setitem__("data_classifications", []), "at least"),
        (lambda s: s.__setitem__("data_classifications", ["unknown"]), "controlled"),
        (lambda s: s.__setitem__("released_artifacts", "bad"), "array"),
        (
            lambda s: s.__setitem__("next_actions", "bad"),
            "next_actions must be an object",
        ),
    ]
    for index, (mutate, message) in enumerate(mutations):
        candidate = copy.deepcopy(service)
        mutate(candidate)
        with pytest.raises(CatalogValidationError, match=message):
            validator.validate_catalog(
                write_service(tmp_path / str(index), "identity_federation", candidate)
            )


def test_contract_database_artifact_and_action_rules_cover_all_failures() -> None:
    """Nested service records must reject mutable, duplicate, and contradictory data."""

    service = load_service()
    contract = service["contracts"][0]
    for field, value, message in (
        ("contract_id", "single", "contract_id"),
        ("contract_kind", "sql", "contract_kind"),
        ("contract_version", "v1", "contract_version"),
        ("immutable_reference", "mutable", "immutable_reference"),
        ("direction", "sideways", "direction"),
        ("maturity", "complete", "maturity"),
    ):
        candidate = copy.deepcopy(contract)
        candidate[field] = value
        with pytest.raises(CatalogValidationError, match=message):
            validate_contract(candidate, "contract")
    duplicate = copy.deepcopy(service)
    duplicate["contracts"].append(copy.deepcopy(duplicate["contracts"][0]))
    with pytest.raises(CatalogValidationError, match="duplicate contract_id"):
        validate_service(duplicate, "service")
    ownership = service["database_ownership"]
    for candidate, message in (
        ({**ownership, "authoritative_service_id": "other_service"}, "must equal"),
        (
            {**ownership, "direct_cross_repository_sql": True},
            "direct cross-repository SQL",
        ),
        ({**ownership, "owns_durable_state": False}, "without durable state"),
        ({**ownership, "owns_durable_state": 1}, "boolean"),
    ):
        with pytest.raises(CatalogValidationError, match=message):
            validate_database_ownership(candidate, "ownership", "identity_federation")
    artifact = {
        "artifact_id": "catalog_schema",
        "artifact_kind": "json_schema",
        "artifact_version": "1.0.0",
        "immutable_reference": "schema:cwl/catalog@1.0.0",
        "maturity": "released",
    }
    validate_artifacts([artifact], "artifacts")
    for candidate, message in (
        (["bad"], r"artifacts\[0\] must be an object"),
        ([artifact, copy.deepcopy(artifact)], "duplicate artifact_id"),
    ):
        with pytest.raises(CatalogValidationError, match=message):
            validate_artifacts(candidate, "artifacts")
    for field, value, message in (
        ("artifact_id", "single", "artifact_id"),
        ("artifact_kind", "other", "artifact_kind"),
        ("artifact_version", "v1", "artifact_version"),
        ("immutable_reference", "mutable", "immutable_reference"),
        ("maturity", "complete", "maturity"),
    ):
        candidate = copy.deepcopy(artifact)
        candidate[field] = value
        with pytest.raises(CatalogValidationError, match=message):
            validate_artifacts([candidate], "artifacts")
    actions = service["next_actions"]
    validate_next_actions(actions, "actions")
    for candidate, message in (
        ({**actions, "extra": "x"}, "unknown"),
        (
            {key: value for key, value in actions.items() if key != "rollback"},
            "missing",
        ),
        ({**actions, "success": ""}, "success"),
    ):
        with pytest.raises(CatalogValidationError, match=message):
            validate_next_actions(candidate, "actions")


def test_manifest_reference_identity_path_repository_and_consumer_uniqueness(
    tmp_path: Path,
) -> None:
    """Referenced manifests must match identity, path, repository, and catalogue membership."""

    cases = []
    catalog = load_catalog()
    catalog["service_manifests"][1]["service_id"] = catalog["service_manifests"][0][
        "service_id"
    ]
    cases.append((catalog, "duplicate service_id"))
    catalog = load_catalog()
    catalog["service_manifests"][1]["manifest_path"] = catalog["service_manifests"][0][
        "manifest_path"
    ]
    cases.append((catalog, "duplicate service manifest path"))
    catalog = load_catalog()
    catalog["service_manifests"][0]["service_id"] = "wrong_service"
    cases.append((catalog, "does not match"))
    catalog = load_catalog()
    catalog["service_manifests"][0]["manifest_path"] = "bad.json"
    cases.append((catalog, "services/"))
    catalog = load_catalog()
    catalog["service_manifests"][0]["extra"] = True
    cases.append((catalog, "unknown"))
    for index, (catalog, message) in enumerate(cases):
        with pytest.raises(CatalogValidationError, match=message):
            validator.validate_catalog(
                write_catalog_tree(tmp_path / str(index), catalog)
            )
    duplicate_repo = load_service("communication_control")
    duplicate_repo["repository"] = load_service("identity_federation")["repository"]
    with pytest.raises(CatalogValidationError, match="duplicate repository"):
        validator.validate_catalog(
            write_service(tmp_path / "repo", "communication_control", duplicate_repo)
        )
    unknown_consumer = load_service()
    unknown_consumer["consumer_repositories"] = ["ContextualWisdomLab/unknown"]
    with pytest.raises(CatalogValidationError, match="uncatalogued consumer"):
        validator.validate_catalog(
            write_service(
                tmp_path / "consumer", "identity_federation", unknown_consumer
            )
        )
