"""Unit tests for the central SBOM inventory aggregator's pure logic."""

import json

import pytest

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
    components = agg.parse_spdx_sbom(SPDX_DOCUMENT)
    names = [c.name for c in components]
    assert "acme-app" not in names
    assert names == ["left-pad", "mystery", "readline"]
    by_name = {c.name: c for c in components}
    assert by_name["left-pad"].license == "MIT"
    assert by_name["readline"].license == "GPL-3.0-or-later"
    assert by_name["mystery"].license == agg.NOASSERTION


def test_parse_cyclonedx_extracts_license_id_and_expression():
    """CycloneDX parsing reads both license.id and expression forms."""
    components = agg.parse_cyclonedx_sbom(CYCLONEDX_DOCUMENT)
    by_name = {c.name: c for c in components}
    assert by_name["requests"].license == "Apache-2.0"
    assert by_name["chardet"].license == "LGPL-2.1-only"
    assert by_name["nameonly"].license == agg.NOASSERTION
    assert "9.9.9" not in {c.name for c in components}


def test_parse_sbom_dispatches_by_format():
    """parse_sbom routes SPDX vs CycloneDX and ignores unknown docs."""
    assert agg.parse_sbom(SPDX_DOCUMENT)
    assert agg.parse_sbom(CYCLONEDX_DOCUMENT)
    assert agg.parse_sbom({"unknown": True}) == []
    assert agg.parse_spdx_sbom({"packages": "bad"}) == []
    assert agg.parse_cyclonedx_sbom({"components": "bad"}) == []


def test_build_inventory_rolls_up_licenses_and_flags():
    """Roll-up aggregates counts, license totals, and policy flags."""
    inventories = [
        agg.RepoInventory(repo="acme/app", components=agg.parse_spdx_sbom(SPDX_DOCUMENT)),
        agg.RepoInventory(repo="acme/lib", components=agg.parse_cyclonedx_sbom(CYCLONEDX_DOCUMENT)),
        agg.RepoInventory(repo="acme/broken", error="sbom unavailable"),
    ]
    inventory = agg.build_inventory(inventories)
    summary = inventory["summary"]
    assert summary["repo_count"] == 3
    assert summary["component_count"] == 6
    # GPL, LGPL, NOASSERTION(x2 from mystery + nameonly) -> 4 flagged.
    assert summary["flagged_count"] == 4
    assert summary["policy"] == "commercial-license-only"
    assert inventory["license_totals"]["MIT"] == 1
    # Repos are sorted; broken repo preserves its error.
    repos = {r["repo"]: r for r in inventory["repos"]}
    assert repos["acme/broken"]["error"] == "sbom unavailable"
    flagged_repos = {item["repo"] for item in inventory["flagged_licenses"]}
    assert flagged_repos == {"acme/app", "acme/lib"}
    # Round-trips as JSON.
    assert json.loads(json.dumps(inventory))["schema"] == "cwl-sbom-inventory/v1"


def test_render_markdown_contains_rollup_and_flags():
    """Markdown renders summary, license roll-up, and flagged components."""
    inventory = agg.build_inventory(
        [agg.RepoInventory(repo="acme/app", components=agg.parse_spdx_sbom(SPDX_DOCUMENT))]
    )
    markdown = agg.render_inventory_markdown(inventory, generated_at="2026-07-08T00:00:00Z")
    assert "# Organization SBOM inventory" in markdown
    assert "2026-07-08T00&#58;00&#58;00Z" in markdown
    assert "GPL-3&#46;0-or-later" in markdown
    assert "commercial-license-only" in markdown
    assert "| readline |" in markdown


def test_render_markdown_handles_empty_and_error_repos():
    """Markdown covers the no-flags, empty-repo, and error-repo branches."""
    inventory = agg.build_inventory(
        [
            agg.RepoInventory(
                repo="acme/clean",
                components=[agg.Component(name="mit-lib", version="1.0", license="MIT")],
            ),
            agg.RepoInventory(repo="acme/empty", components=[]),
            agg.RepoInventory(repo="acme/broken", error="not found"),
        ]
    )
    markdown = agg.render_inventory_markdown(inventory, generated_at="now")
    assert "No copyleft or NOASSERTION components detected." in markdown
    assert "No components reported." in markdown
    assert "SBOM unavailable: not found" in markdown


def test_write_inventory_emits_both_files(tmp_path):
    """write_inventory produces inventory.json and inventory.md."""
    inventory = agg.build_inventory(
        [agg.RepoInventory(repo="acme/app", components=agg.parse_spdx_sbom(SPDX_DOCUMENT))]
    )
    markdown = agg.render_inventory_markdown(inventory, generated_at="now")
    agg.write_inventory(inventory, markdown, tmp_path / "sbom")
    written = json.loads((tmp_path / "sbom" / "inventory.json").read_text())
    assert written["summary"]["repo_count"] == 1
    assert (tmp_path / "sbom" / "inventory.md").read_text().startswith("# Organization SBOM inventory")


def test_self_test_passes(capsys):
    """The bundled self-test runs clean and prints its sentinel."""
    agg.self_test()
    assert "self-test passed" in capsys.readouterr().out


@pytest.mark.parametrize(
    "repo",
    [
        "--repo=attacker/repo",
        "owner",
        "owner/repo/extra",
        "owner/-R",
        "owner/bad repo",
        "owner/..",
        "double--hyphen/repo",
    ],
)
def test_validate_repo_full_name_rejects_unsafe_values(repo):
    """Explicit repository inputs must be canonical full names."""
    with pytest.raises(ValueError, match="repository full name"):
        agg._validate_repo_full_name(repo)


def test_validate_repo_full_name_accepts_github_dot_repository():
    """The organization's special dot repository remains a valid target."""
    assert (
        agg._validate_repo_full_name("ContextualWisdomLab/.github")
        == "ContextualWisdomLab/.github"
    )


def test_validate_owner_login_rejects_unsafe_values():
    """Organization discovery operands must be canonical logins."""
    with pytest.raises(ValueError, match="organization login"):
        agg._validate_owner_login("bad org")
    with pytest.raises(ValueError, match="organization login"):
        agg._validate_owner_login(None)


def test_list_org_repos_rejects_unsafe_name_returned_by_gh(monkeypatch):
    """Discovery output is untrusted until every full name is validated."""
    monkeypatch.setattr(
        agg,
        "_run",
        lambda _args: '[{"nameWithOwner":"ContextualWisdomLab/bad repo"}]',
    )

    with pytest.raises(ValueError, match="repository full name"):
        agg.list_org_repos("ContextualWisdomLab")


def test_arg_parser_defaults():
    """CLI parser exposes org/output-dir/repo/self-test with sane defaults."""
    parser = agg.build_arg_parser()
    args = parser.parse_args([])
    assert args.org == "ContextualWisdomLab"
    assert args.output_dir == "docs/sbom"
    assert args.repos is None
    args = parser.parse_args(["--repo", "a/b", "--repo", "c/d", "--self-test"])
    assert args.repos == ["a/b", "c/d"]
    assert args.self_test is True
