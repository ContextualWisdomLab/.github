"""Naming-contract regressions for the organization SBOM inventory domain."""

from dataclasses import fields

from scripts.ci import sbom_inventory_aggregator as agg


def test_internal_sbom_models_use_semantic_identifiers() -> None:
    """Owned SBOM models keep generic vocabulary at compatibility boundaries only."""

    component_field_names = {field.name for field in fields(agg.SbomComponent)}
    repository_inventory_field_names = {
        field.name for field in fields(agg.RepositorySbomInventory)
    }

    assert component_field_names == {
        "component_name",
        "component_version",
        "license_expression",
    }
    assert repository_inventory_field_names == {
        "repository_name",
        "software_components",
        "fetch_error",
    }
    assert not hasattr(agg, "Component")
    assert not hasattr(agg, "RepoInventory")


def test_legacy_v1_inventory_adapter_preserves_existing_wire_keys() -> None:
    """The semantic internal model must not break the published v1 inventory shape."""

    sbom_component = agg.SbomComponent(
        component_name="example-lib",
        component_version="1.2.3",
        license_expression="MIT",
    )
    repository_inventory = agg.RepositorySbomInventory(
        repository_name="ContextualWisdomLab/example",
        software_components=[sbom_component],
    )

    inventory_payload = agg.build_inventory([repository_inventory])
    repository_payload = inventory_payload["repos"][0]
    component_payload = repository_payload["components"][0]

    assert inventory_payload["schema"] == "cwl-sbom-inventory/v1"
    assert repository_payload["repo"] == "ContextualWisdomLab/example"
    assert set(component_payload) == {"name", "version", "license", "flagged"}
    assert component_payload["name"] == "example-lib"
    assert component_payload["version"] == "1.2.3"
    assert component_payload["license"] == "MIT"
    assert "component_name" not in component_payload
