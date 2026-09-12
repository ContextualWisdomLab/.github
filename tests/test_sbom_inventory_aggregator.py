"""Unit tests for the central SBOM inventory aggregator's pure logic."""

import json

from scripts.ci import sbom_inventory_aggregator as agg


SPDX_DOCUMENT = {
    "spdxVersion": "SPDX-2.3",
    "SPDXID": "SPDXRef-DOCUMENT",
    "packages": [
        {"SPDXID": "SPDXRef-root", "name": "acme-app", "versionInfo": "0.0.0"},
        {"SPDXID": "SPDXRef-a", "name": "left-pad", "versionInfo": "1.3.0", "licenseConcluded": "MIT"},
        {"SPDXID": "SPDXRef-b", "name": "readline", "versionInfo": "8.2", "licenseDeclared": "GPL-3.0-or-later"},
        {"SPDXID": "SPDXRef-c", "name": "mystery", "versionInfo": "0.1.0"},
        {"SPDXID": "SPDXRef-noname", "versionInfo": "0.0.1"},
        "not-a-dict-package",
    ],
    "relationships": [
        {"relationshipType": "DESCRIBES", "relatedSpdxElement": "SPDXRef-root"},
        {"relationshipType": "DEPENDS_ON", "relatedSpdxElement": "SPDXRef-a"},
        "not-a-dict",
    ],
}

CYCLONEDX_DOCUMENT = {
    "bomFormat": "CycloneDX",
    "components": [
        {"name": "requests", "version": "2.31.0", "licenses": [{"license": {"id": "Apache-2.0"}}]},
        {"name": "chardet", "version": "5.0.0", "licenses": ["not-a-dict", {"expression": "LGPL-2.1-only"}]},
        {"name": "nameonly"},
        {"version": "9.9.9"},
        "not-a-dict",
    ],
}


def test_is_flagged_license_matches_copyleft_and_unknown():
    """Copyleft families and NOASSERTION/NONE are flagged; permissive is not."""
    assert agg.is_flagged_license("GPL-3.0-or-later")
    assert agg.is_flagged_license("AGPL-3.0-only")
    assert agg.is_flagged_license("LGPL-2.1")
    assert agg.is_flagged_license("MPL-2.0")
    assert agg.is_flagged_license("NOASSERTION")
    assert agg.is_flagged_license("NONE")
    assert agg.is_flagged_license("")
    assert agg.is_flagged_license(None)
    assert not agg.is_flagged_license("MIT")
    assert not agg.is_flagged_license("Apache-2.0")
    assert not agg.is_flagged_license("BSD-3-Clause")


def test_normalize_license_defaults_to_noassertion():
    """Blank and None license fields normalize to NOASSERTION."""
    assert agg.normalize_license(None) == agg.NOASSERTION
    assert agg.normalize_license("  ") == agg.NOASSERTION
    assert agg.normalize_license("  MIT ") == "MIT"


def test_parse_spdx_skips_root_and_defaults_license():
    """SPDX parsing drops the DESCRIBES root and defaults missing licenses."""
    sbom_components = agg.parse_spdx_sbom(SPDX_DOCUMENT)
    component_names = [component.component_name for component in sbom_components]
    assert "acme-app" not in component_names
    assert component_names == ["left-pad", "mystery", "readline"]
    components_by_name = {
        component.component_name: component for component in sbom_components
    }
    assert components_by_name["left-pad"].license_expression == "MIT"
    assert components_by_name["readline"].license_expression == "GPL-3.0-or-later"
    assert components_by_name["mystery"].license_expression == agg.NOASSERTION


def test_parse_cyclonedx_extracts_license_id_and_expression():
    """CycloneDX parsing reads both license.id and expression forms."""
    sbom_components = agg.parse_cyclonedx_sbom(CYCLONEDX_DOCUMENT)
    components_by_name = {
        component.component_name: component for component in sbom_components
    }
    assert components_by_name["requests"].license_expression == "Apache-2.0"
    assert components_by_name["chardet"].license_expression == "LGPL-2.1-only"
    assert components_by_name["nameonly"].license_expression == agg.NOASSERTION
    assert "9.9.9" not in {
        component.component_name for component in sbom_components
    }


def test_parse_sbom_dispatches_by_format():
    """parse_sbom routes SPDX vs CycloneDX and ignores unknown docs."""
    assert agg.parse_sbom(SPDX_DOCUMENT)
    assert agg.parse_sbom(CYCLONEDX_DOCUMENT)
    assert agg.parse_sbom({"unknown": True}) == []
    assert agg.parse_spdx_sbom({"packages": "bad"}) == []
    assert agg.parse_cyclonedx_sbom({"components": "bad"}) == []


def test_build_inventory_rolls_up_licenses_and_flags():
    """Roll-up aggregates counts, license totals, and policy flags."""
    repository_inventories = [
        agg.RepositorySbomInventory(
            repository_name="acme/app",
            software_components=agg.parse_spdx_sbom(SPDX_DOCUMENT),
        ),
        agg.RepositorySbomInventory(
            repository_name="acme/lib",
            software_components=agg.parse_cyclonedx_sbom(CYCLONEDX_DOCUMENT),
        ),
        agg.RepositorySbomInventory(
            repository_name="acme/broken", fetch_error="sbom unavailable"
        ),
    ]
    inventory_payload = agg.build_inventory(repository_inventories)
    summary_payload = inventory_payload["summary"]
    assert summary_payload["repo_count"] == 3
    assert summary_payload["component_count"] == 6
    # GPL, LGPL, NOASSERTION(x2 from mystery + nameonly) -> 4 flagged.
    assert summary_payload["flagged_count"] == 4
    assert summary_payload["policy"] == "commercial-license-only"
    assert inventory_payload["license_totals"]["MIT"] == 1
    # Repos are sorted; broken repo preserves its error. The keys are v1 wire compatibility.
    repository_payloads = {
        repository_payload["repo"]: repository_payload
        for repository_payload in inventory_payload["repos"]
    }
    assert repository_payloads["acme/broken"]["error"] == "sbom unavailable"
    flagged_repository_names = {
        license_record["repo"] for license_record in inventory_payload["flagged_licenses"]
    }
    assert flagged_repository_names == {"acme/app", "acme/lib"}
    # Round-trips as the published JSON contract.
    assert json.loads(json.dumps(inventory_payload))["schema"] == "cwl-sbom-inventory/v1"


def test_render_markdown_contains_rollup_and_flags():
    """Markdown renders summary, license roll-up, and flagged components."""
    inventory_payload = agg.build_inventory(
        [
            agg.RepositorySbomInventory(
                repository_name="acme/app",
                software_components=agg.parse_spdx_sbom(SPDX_DOCUMENT),
            )
        ]
    )
    inventory_markdown = agg.render_inventory_markdown(
        inventory_payload, generated_at="2026-07-08T00:00:00Z"
    )
    assert "# Organization SBOM inventory" in inventory_markdown
    assert "2026-07-08T00:00:00Z" in inventory_markdown
    assert "GPL-3.0-or-later" in inventory_markdown
    assert "commercial-license-only" in inventory_markdown
    assert "| readline |" in inventory_markdown


def test_render_markdown_handles_empty_and_error_repos():
    """Markdown covers the no-flags, empty-repo, and error-repo branches."""
    inventory_payload = agg.build_inventory(
        [
            agg.RepositorySbomInventory(
                repository_name="acme/clean",
                software_components=[
                    agg.SbomComponent(
                        component_name="mit-lib",
                        component_version="1.0",
                        license_expression="MIT",
                    )
                ],
            ),
            agg.RepositorySbomInventory(
                repository_name="acme/empty", software_components=[]
            ),
            agg.RepositorySbomInventory(
                repository_name="acme/broken", fetch_error="not found"
            ),
        ]
    )
    inventory_markdown = agg.render_inventory_markdown(
        inventory_payload, generated_at="now"
    )
    assert "No copyleft or NOASSERTION components detected." in inventory_markdown
    assert "No components reported." in inventory_markdown
    assert "SBOM unavailable: not found" in inventory_markdown


def test_write_inventory_emits_both_files(tmp_path):
    """write_inventory produces inventory.json and inventory.md."""
    inventory_payload = agg.build_inventory(
        [
            agg.RepositorySbomInventory(
                repository_name="acme/app",
                software_components=agg.parse_spdx_sbom(SPDX_DOCUMENT),
            )
        ]
    )
    inventory_markdown = agg.render_inventory_markdown(
        inventory_payload, generated_at="now"
    )
    agg.write_inventory(inventory_payload, inventory_markdown, tmp_path / "sbom")
    written_inventory = json.loads(
        (tmp_path / "sbom" / "inventory.json").read_text()
    )
    assert written_inventory["summary"]["repo_count"] == 1
    assert (tmp_path / "sbom" / "inventory.md").read_text().startswith(
        "# Organization SBOM inventory"
    )


def test_self_test_passes(capsys):
    """The bundled self-test runs clean and prints its sentinel."""
    agg.self_test()
    assert "self-test passed" in capsys.readouterr().out


def test_arg_parser_defaults():
    """CLI flags translate to semantic internal destinations with sane defaults."""
    argument_parser = agg.build_arg_parser()
    cli_arguments = argument_parser.parse_args([])
    assert cli_arguments.organization_name == "ContextualWisdomLab"
    assert cli_arguments.output_directory == "docs/sbom"
    assert cli_arguments.repository_names is None
    assert cli_arguments.generated_timestamp == ""
    assert cli_arguments.self_test_requested is False

    cli_arguments = argument_parser.parse_args(
        ["--repo", "a/b", "--repo", "c/d", "--self-test"]
    )
    assert cli_arguments.repository_names == ["a/b", "c/d"]
    assert cli_arguments.self_test_requested is True
