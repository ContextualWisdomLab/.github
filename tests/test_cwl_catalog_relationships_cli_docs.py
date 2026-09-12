"""Relationship, CLI, documentation, and workflow tests for the CWL catalogue."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest
from catalogue_test_helpers import (
    CATALOG,
    ROOT,
    load_catalog,
    load_service,
    validator,
    write_catalog_tree,
    write_service,
)
from cwl_catalog_contract import CatalogValidationError

DOC = ROOT / "docs/integration/CWL_REPOSITORY_RESPONSIBILITY_CATALOG.md"
INDEX = ROOT / "docs/integration/README.md"
CHANGELOG = ROOT / "CHANGELOG.md"
ADR = ROOT / "docs/integration/adr/0002-cwl-capability-catalog.md"
DOCTORING = ROOT / "docs/doctoring/ecosystem-capability-catalog-standards.md"
WORKFLOW = ROOT / ".github/workflows/cwl-ecosystem-catalog-quality-ci.yml"
PRODUCTION = tuple((ROOT / "scripts/ci").glob("cwl_catalog_*.py")) + (
    ROOT / "scripts/ci/validate_cwl_ecosystem_catalog.py",
)


def first_relation(catalog: dict[str, object]) -> dict[str, object]:
    """Return the first positive relationship."""

    relationships = catalog["relationships"]
    assert isinstance(relationships, list) and isinstance(relationships[0], dict)
    return relationships[0]


def invalid_relation(tmp_path: Path, field: str, value: object, message: str) -> None:
    """Require one relationship mutation to fail with an operator-readable reason."""

    catalog = load_catalog()
    first_relation(catalog)[field] = value
    with pytest.raises(CatalogValidationError, match=message):
        validator.validate_catalog(write_catalog_tree(tmp_path, catalog))


def test_relationship_fields_security_and_unknown_services_are_strict(
    tmp_path: Path,
) -> None:
    """Relationship identity, vocabulary, service references, and unsafe flags must fail closed."""

    cases = (
        ("relationship_id", "single", "relationship_id"),
        ("provider_service_id", "unknown_service", "unknown provider"),
        ("consumer_service_id", "unknown_service", "unknown consumer"),
        (
            "authoritative_data_owner_service_id",
            "unknown_service",
            "unknown authoritative",
        ),
        ("contract_kind", "sql", "contract_kind"),
        ("contract_version", "v1", "contract_version"),
        ("immutable_reference", "mutable", "immutable_reference"),
        ("purpose_code", "single", "purpose_code"),
        ("data_classification", "unknown", "data_classification"),
        ("data_flow_class", "raw_copy", "data_flow_class"),
        ("evidence_class", "guess", "evidence_class"),
        ("maturity", "complete", "maturity"),
        ("credential_flow", "copied", "credential_flow"),
        ("direct_cross_repository_sql", True, "direct cross-repository SQL"),
        ("credential_copying", True, "credential copying"),
        ("raw_pii_broadcast", True, "raw PII broadcast"),
        ("may_update_authoritative_fact", "yes", "boolean"),
    )
    for index, (field, value, message) in enumerate(cases):
        invalid_relation(tmp_path / str(index), field, value, message)


def test_relationship_graph_data_flow_authority_and_maturity_invariants(
    tmp_path: Path,
) -> None:
    """Self-edges, inference authority, false data classes, and maturity overstatement must fail."""

    mutations = [
        (lambda r: r.__setitem__("extra", True), "unknown properties"),
        (lambda r: r.pop("contract_kind"), "missing properties"),
        (
            lambda r: r.__setitem__("consumer_service_id", r["provider_service_id"]),
            "self-edge",
        ),
        (
            lambda r: (
                r.__setitem__("evidence_class", "inferred_relationship"),
                r.__setitem__("may_update_authoritative_fact", True),
            ),
            "inferred relationship",
        ),
        (
            lambda r: (
                r.__setitem__("data_flow_class", "no_business_data"),
                r.__setitem__("data_classification", "restricted_identity"),
            ),
            "no_business_data",
        ),
        (
            lambda r: (
                r.__setitem__("contract_kind", "build_control"),
                r.__setitem__("data_flow_class", "purpose_bound_projection"),
            ),
            "build_control",
        ),
        (
            lambda r: (
                r.__setitem__("data_classification", "restricted_identity"),
                r.__setitem__("data_flow_class", "schema_contract"),
            ),
            "restricted data",
        ),
        (
            lambda r: (
                r.__setitem__("may_update_authoritative_fact", True),
                r.__setitem__(
                    "authoritative_data_owner_service_id", "identity_federation"
                ),
            ),
            "authoritative consumer",
        ),
        (lambda r: r.__setitem__("maturity", "released"), "exceeds endpoint maturity"),
    ]
    for index, (mutate, message) in enumerate(mutations):
        catalog = load_catalog()
        mutate(first_relation(catalog))
        with pytest.raises(CatalogValidationError, match=message):
            validator.validate_catalog(
                write_catalog_tree(tmp_path / str(index), catalog)
            )
    catalog = load_catalog()
    catalog["relationships"][1]["relationship_id"] = catalog["relationships"][0][
        "relationship_id"
    ]
    with pytest.raises(CatalogValidationError, match="duplicate relationship_id"):
        validator.validate_catalog(write_catalog_tree(tmp_path / "duplicate", catalog))
    catalog = load_catalog()
    catalog["relationships"][0] = "bad"
    with pytest.raises(
        CatalogValidationError, match=r"relationships\[0\] must be an object"
    ):
        validator.validate_catalog(write_catalog_tree(tmp_path / "shape", catalog))


def test_authoritative_update_is_accepted_only_at_authoritative_consumer(
    tmp_path: Path,
) -> None:
    """An explicitly authorized command may update only the authoritative consumer."""

    catalog = load_catalog()
    relation = first_relation(catalog)
    relation["authoritative_data_owner_service_id"] = "orgmetra_hris"
    relation["may_update_authoritative_fact"] = True
    validator.validate_catalog(write_catalog_tree(tmp_path, catalog))


def test_relationship_requires_provider_consumer_declaration(tmp_path: Path) -> None:
    """A relationship edge must be declared by the provider manifest too."""

    catalog = load_catalog()
    relation = first_relation(catalog)
    provider_id = str(relation["provider_service_id"])
    provider = load_service(provider_id)
    provider["consumer_repositories"] = []

    with pytest.raises(
        CatalogValidationError,
        match="consumer repository is not declared by provider service",
    ):
        validator.validate_catalog(write_service(tmp_path, provider_id, provider))


def test_documentation_workflow_and_docstrings_are_complete() -> None:
    """Buyer guidance, standards, immutable CI, and production docstrings must remain complete."""

    for path in (DOC, INDEX, CHANGELOG, ADR, DOCTORING, WORKFLOW):
        assert path.is_file()
    text = DOC.read_text(encoding="utf-8").lower()
    for token in (
        "authoritative data owner",
        "direct cross-repository sql",
        "purpose-bound",
        "raw pii",
        "csap",
        "soc 2",
        "customer next action",
        "rollback",
    ):
        assert token in text
    index = INDEX.read_text(encoding="utf-8")
    assert "CWL_ECOSYSTEM_INTEGRATION_CONTRACT.md" in index
    assert "CWL_REPOSITORY_RESPONSIBILITY_CATALOG.md" in index
    assert (
        "repository responsibility catalogue"
        in CHANGELOG.read_text(encoding="utf-8").lower()
    )
    adr = ADR.read_text(encoding="utf-8")
    assert "## Decision" in adr and "## Consequences" in adr
    doctoring = DOCTORING.read_text(encoding="utf-8")
    for token in (
        "JSON Schema Draft 2020-12",
        "OpenAPI 3.2.0",
        "AsyncAPI 3.1.0",
        "CloudEvents 1.0",
        "W3C PROV-O",
    ):
        assert token in doctoring
    workflow = WORKFLOW.read_text(encoding="utf-8")
    for token in (
        "contents: read",
        "persist-credentials: false",
        "coverage run --branch",
        "--fail-under=100",
        "github.event.pull_request.head.sha",
    ):
        assert token in workflow
    for path in PRODUCTION:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert ast.get_docstring(tree)
        assert [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and not ast.get_docstring(node)
        ] == []


def test_cli_and_callable_entry_points_use_stable_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI and callable entry points must emit bounded success and failure results."""

    script = ROOT / "scripts/ci/validate_cwl_ecosystem_catalog.py"
    accepted = subprocess.run(
        [sys.executable, str(script), str(CATALOG)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert (
        accepted.returncode == 0
        and "validated" in accepted.stdout
        and accepted.stderr == ""
    )
    packaged = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.ci.validate_cwl_ecosystem_catalog",
            str(CATALOG),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert (
        packaged.returncode == 0
        and "validated" in packaged.stdout
        and packaged.stderr == ""
    )
    catalog = load_catalog()
    first_relation(catalog)["direct_cross_repository_sql"] = True
    rejected_path = write_catalog_tree(tmp_path / "rejected", catalog)
    rejected = subprocess.run(
        [sys.executable, str(script), str(rejected_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert (
        rejected.returncode == 2
        and rejected.stdout == ""
        and "validation failed" in rejected.stderr
        and len(rejected.stderr) < 1024
    )
    assert validator.main([str(CATALOG)]) == 0
    assert "validated" in capsys.readouterr().out
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    assert validator.main([str(bad)]) == 2
    assert "validation failed" in capsys.readouterr().err

    def raise_os_error(path: Path) -> None:
        """Raise one synthetic filesystem failure."""
        raise OSError("synthetic")

    monkeypatch.setattr(validator, "validate_catalog", raise_os_error)
    assert validator.main([str(CATALOG)]) == 2
    assert "could not read catalogue" in capsys.readouterr().err
    assert validator.main([]) == 2
    assert "usage:" in capsys.readouterr().err
