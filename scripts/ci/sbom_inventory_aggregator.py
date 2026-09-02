#!/usr/bin/env python3
"""Aggregate every managed repository's SBOM into one central org inventory.

This script is the "centralize" half of the ContextualWisdomLab SBOM pipeline.
The per-repository ``SBOM Generation`` workflow submits each repo's dependency
snapshot to the GitHub dependency graph; this aggregator reads that graph back
out (``GET /repos/{owner}/{repo}/dependency-graph/sbom`` returns SPDX), parses
the components + licenses, and writes a consolidated inventory:

    docs/sbom/inventory.json   machine-readable component roll-up
    docs/sbom/inventory.md     human-readable component + license roll-up

The license roll-up flags any GPL/AGPL/copyleft/NOASSERTION component against
the organization's commercial-license-only policy so governance has one place
to see policy-relevant licenses across the whole org.

Configuration is passed as CLI arguments (the calling workflow wires them from
CI vars/secrets); the only environment coupling is ``gh``'s own ``GH_TOKEN``,
which the workflow exports for cross-repository reads.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

SBOM_FETCH_WORKERS = 10

# Licenses that violate the commercial-license-only policy. Matched as
# case-insensitive substrings against the normalized SPDX license expression so
# variants like "LGPL-3.0-or-later" or "AGPL-3.0-only" are all caught.
COPYLEFT_LICENSE_MARKERS: tuple[str, ...] = (
    "GPL",
    "AGPL",
    "LGPL",
    "MPL",
    "EPL",
    "CDDL",
    "CC-BY-SA",
    "SSPL",
    "OSL",
    "EUPL",
)

# Sentinel emitted by SBOM tooling when it cannot determine a license.
NOASSERTION = "NOASSERTION"


@dataclass(frozen=True)
class SbomComponent:
    """A software component discovered in one repository SBOM."""

    component_name: str
    component_version: str
    license_expression: str


@dataclass
class RepositorySbomInventory:
    """Parsed SBOM result for one repository."""

    repository_name: str
    software_components: list[SbomComponent] = field(default_factory=list)
    fetch_error: str | None = None


def normalize_license(license_value: Any) -> str:
    """Return a trimmed license string, defaulting to NOASSERTION."""
    if license_value is None:
        return NOASSERTION
    license_text = str(license_value).strip()
    if not license_text:
        return NOASSERTION
    return license_text


def is_flagged_license(license_expression: str) -> bool:
    """Return True when a license is copyleft/unknown under the policy."""
    normalized_license = normalize_license(license_expression)
    upper_license = normalized_license.upper()
    if upper_license == NOASSERTION or upper_license == "NONE":
        return True
    return any(marker in upper_license for marker in COPYLEFT_LICENSE_MARKERS)


def _spdx_license(spdx_package: dict[str, Any]) -> str:
    """Pick the most specific SPDX license field available on a package."""
    for license_key in ("licenseConcluded", "licenseDeclared"):
        license_candidate = normalize_license(spdx_package.get(license_key))
        if license_candidate != NOASSERTION:
            return license_candidate
    return NOASSERTION


def parse_spdx_sbom(spdx_document: dict[str, Any]) -> list[SbomComponent]:
    """Parse an SPDX document into components, skipping its DESCRIBES root."""
    spdx_packages = spdx_document.get("packages")
    if not isinstance(spdx_packages, list):
        return []
    described_element_ids = _spdx_described_ids(spdx_document)
    sbom_components: list[SbomComponent] = []
    for spdx_package in spdx_packages:
        if not isinstance(spdx_package, dict):
            continue
        component_name = normalize_license(spdx_package.get("name"))
        if component_name == NOASSERTION:
            continue
        if spdx_package.get("SPDXID") in described_element_ids:
            # SPDX owns these generic keys; the described package is the repo itself.
            continue
        component_version = spdx_package.get("versionInfo")
        sbom_components.append(
            SbomComponent(
                component_name=str(component_name),
                component_version=(
                    normalize_license(component_version) if component_version else ""
                ),
                license_expression=_spdx_license(spdx_package),
            )
        )
    return _dedupe(sbom_components)


def _spdx_described_ids(spdx_document: dict[str, Any]) -> set[str]:
    """Collect SPDXIDs the document DESCRIBES (its own root package)."""
    described_element_ids: set[str] = set()
    spdx_relationships = spdx_document.get("relationships")
    if isinstance(spdx_relationships, list):
        for spdx_relationship in spdx_relationships:
            if not isinstance(spdx_relationship, dict):
                continue
            if spdx_relationship.get("relationshipType") == "DESCRIBES":
                related_element_id = spdx_relationship.get("relatedSpdxElement")
                if isinstance(related_element_id, str):
                    described_element_ids.add(related_element_id)
    return described_element_ids


def _cyclonedx_license(cyclonedx_component: dict[str, Any]) -> str:
    """Extract a license expression from a CycloneDX component entry."""
    license_entries = cyclonedx_component.get("licenses")
    if isinstance(license_entries, list):
        for license_entry in license_entries:
            if not isinstance(license_entry, dict):
                continue
            if "expression" in license_entry:
                return normalize_license(license_entry.get("expression"))
            license_document = license_entry.get("license")
            if isinstance(license_document, dict):
                license_candidate = license_document.get("id") or license_document.get("name")
                normalized_license = normalize_license(license_candidate)
                if normalized_license != NOASSERTION:
                    return normalized_license
    return NOASSERTION


def parse_cyclonedx_sbom(cyclonedx_document: dict[str, Any]) -> list[SbomComponent]:
    """Parse a CycloneDX document into components."""
    raw_components = cyclonedx_document.get("components")
    if not isinstance(raw_components, list):
        return []
    sbom_components: list[SbomComponent] = []
    for cyclonedx_component in raw_components:
        if not isinstance(cyclonedx_component, dict):
            continue
        component_name = cyclonedx_component.get("name")
        if not component_name:
            continue
        component_version = cyclonedx_component.get("version")
        sbom_components.append(
            SbomComponent(
                component_name=str(component_name),
                component_version=str(component_version) if component_version else "",
                license_expression=_cyclonedx_license(cyclonedx_component),
            )
        )
    return _dedupe(sbom_components)


def parse_sbom(sbom_document: dict[str, Any]) -> list[SbomComponent]:
    """Parse either an SPDX or CycloneDX document into components."""
    if "spdxVersion" in sbom_document or "SPDXID" in sbom_document:
        return parse_spdx_sbom(sbom_document)
    if sbom_document.get("bomFormat") == "CycloneDX" or "components" in sbom_document:
        return parse_cyclonedx_sbom(sbom_document)
    return []


def _dedupe(sbom_components: Iterable[SbomComponent]) -> list[SbomComponent]:
    """Return components sorted and deduplicated by semantic component identity."""
    unique_components = {
        (
            sbom_component.component_name,
            sbom_component.component_version,
            sbom_component.license_expression,
        ): sbom_component
        for sbom_component in sbom_components
    }
    return sorted(
        unique_components.values(),
        key=lambda sbom_component: (
            sbom_component.component_name.lower(),
            sbom_component.component_version,
        ),
    )


def build_inventory(
    repository_inventories: Sequence[RepositorySbomInventory],
) -> dict[str, Any]:
    """Adapt semantic SBOM records into the published ``cwl-sbom-inventory/v1`` shape.

    The generic JSON keys in this function are the compatibility boundary for the
    already-published v1 artifact. Organization-owned Python names stay specific;
    SPDX/CycloneDX vendor keys and this v1 wire shape remain unchanged.
    """
    repository_payloads: list[dict[str, Any]] = []
    license_totals: dict[str, int] = {}
    flagged_license_records: list[dict[str, str]] = []
    total_component_count = 0

    for repository_inventory in sorted(
        repository_inventories,
        key=lambda inventory_record: inventory_record.repository_name.lower(),
    ):
        component_payloads = [
            {
                "name": sbom_component.component_name,
                "version": sbom_component.component_version,
                "license": sbom_component.license_expression,
                "flagged": is_flagged_license(sbom_component.license_expression),
            }
            for sbom_component in repository_inventory.software_components
        ]
        total_component_count += len(component_payloads)
        for sbom_component in repository_inventory.software_components:
            license_key = normalize_license(sbom_component.license_expression)
            license_totals[license_key] = license_totals.get(license_key, 0) + 1
            if is_flagged_license(license_key):
                flagged_license_records.append(
                    {
                        "repo": repository_inventory.repository_name,
                        "name": sbom_component.component_name,
                        "version": sbom_component.component_version,
                        "license": license_key,
                    }
                )
        repository_payloads.append(
            {
                "repo": repository_inventory.repository_name,
                "error": repository_inventory.fetch_error,
                "component_count": len(component_payloads),
                "components": component_payloads,
            }
        )

    flagged_license_records.sort(
        key=lambda license_record: (
            license_record["repo"].lower(),
            license_record["name"].lower(),
        )
    )
    return {
        "schema": "cwl-sbom-inventory/v1",
        "summary": {
            "repo_count": len(repository_payloads),
            "component_count": total_component_count,
            "flagged_count": len(flagged_license_records),
            "policy": "commercial-license-only",
        },
        "license_totals": dict(sorted(license_totals.items())),
        "flagged_licenses": flagged_license_records,
        "repos": repository_payloads,
    }


def render_inventory_markdown(
    inventory_payload: dict[str, Any], *, generated_at: str
) -> str:
    """Render the consolidated v1 inventory as a governance-facing markdown page."""
    summary_payload = inventory_payload["summary"]
    markdown_lines: list[str] = [
        "# Organization SBOM inventory",
        "",
        f"Generated: {generated_at}",
        "",
        "One central view of every managed repository's software components,",
        "versions, and licenses. Feeds license and vulnerability governance",
        "alongside the central Security Scan.",
        "",
        "## Summary",
        "",
        f"- Repositories: {summary_payload['repo_count']}",
        f"- Components: {summary_payload['component_count']}",
        f"- Policy: {summary_payload['policy']}",
        f"- Flagged licenses: {summary_payload['flagged_count']}",
        "",
        "## License roll-up",
        "",
        "| License | Components |",
        "| --- | ---: |",
    ]
    for license_key, license_count in inventory_payload["license_totals"].items():
        policy_flag = " ⚠️" if is_flagged_license(license_key) else ""
        markdown_lines.append(f"| {license_key}{policy_flag} | {license_count} |")

    markdown_lines.extend(["", "## Flagged components (policy violations)", ""])
    if inventory_payload["flagged_licenses"]:
        markdown_lines.extend(
            [
                "| Repository | Component | Version | License |",
                "| --- | --- | --- | --- |",
            ]
        )
        for license_record in inventory_payload["flagged_licenses"]:
            markdown_lines.append(
                f"| {license_record['repo']} | {license_record['name']} | "
                f"{license_record['version'] or '—'} | {license_record['license']} |"
            )
    else:
        markdown_lines.append("No copyleft or NOASSERTION components detected.")

    markdown_lines.extend(["", "## Per-repository components", ""])
    for repository_payload in inventory_payload["repos"]:
        markdown_lines.append(f"### {repository_payload['repo']}")
        markdown_lines.append("")
        if repository_payload["error"]:
            markdown_lines.append(f"SBOM unavailable: {repository_payload['error']}")
            markdown_lines.append("")
            continue
        if not repository_payload["components"]:
            markdown_lines.append("No components reported.")
            markdown_lines.append("")
            continue
        markdown_lines.extend(
            ["| Component | Version | License | Flagged |", "| --- | --- | --- | --- |"]
        )
        for component_payload in repository_payload["components"]:
            policy_flag = "yes" if component_payload["flagged"] else "no"
            markdown_lines.append(
                f"| {component_payload['name']} | {component_payload['version'] or '—'} | "
                f"{component_payload['license']} | {policy_flag} |"
            )
        markdown_lines.append("")
    return "\n".join(markdown_lines).rstrip() + "\n"


def write_inventory(
    inventory_payload: dict[str, Any],
    inventory_markdown: str,
    output_directory: Path,
) -> None:
    """Write the JSON and markdown inventory artifacts to ``output_directory``."""
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "inventory.json").write_text(
        json.dumps(inventory_payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    (output_directory / "inventory.md").write_text(inventory_markdown, encoding="utf-8")


def _run(command_args: Sequence[str]) -> str:  # pragma: no cover - thin subprocess wrapper
    """Run a command and return stdout, raising on failure."""
    completed_process = subprocess.run(
        list(command_args), capture_output=True, text=True, check=True
    )
    return completed_process.stdout


def list_org_repos(organization_name: str) -> list[str]:  # pragma: no cover - network
    """List non-archived repositories for an organization via gh."""
    repository_listing_json = _run(
        [
            "gh",
            "repo",
            "list",
            organization_name,
            "--no-archived",
            "--limit",
            "500",
            "--json",
            "nameWithOwner",
        ]
    )
    return [
        repository_entry["nameWithOwner"]
        for repository_entry in json.loads(repository_listing_json or "[]")
    ]


def fetch_repo_sbom(repository_name: str) -> RepositorySbomInventory:  # pragma: no cover - network
    """Fetch and parse one repository's dependency-graph SBOM via gh."""
    try:
        sbom_response_json = _run(
            ["gh", "api", f"/repos/{repository_name}/dependency-graph/sbom"]
        )
    except subprocess.CalledProcessError as fetch_exception:
        error_lines = (fetch_exception.stderr or "").strip().splitlines()
        return RepositorySbomInventory(
            repository_name=repository_name,
            fetch_error=error_lines[-1] if error_lines else "sbom unavailable",
        )
    sbom_response_payload = json.loads(sbom_response_json or "{}")
    sbom_document = sbom_response_payload.get("sbom", sbom_response_payload)
    return RepositorySbomInventory(
        repository_name=repository_name,
        software_components=parse_sbom(sbom_document),
    )


def collect_inventories(
    repository_names: Sequence[str],
) -> list[RepositorySbomInventory]:  # pragma: no cover - network
    """Fetch every repository's SBOM into per-repository inventories."""
    if len(repository_names) <= 1:
        return [fetch_repo_sbom(repository_name) for repository_name in repository_names]

    worker_count = min(SBOM_FETCH_WORKERS, len(repository_names))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        # Keep original order by using map and converting to list.
        return list(executor.map(fetch_repo_sbom, repository_names))


def self_test() -> None:
    """Run in-process assertions covering parse, roll-up, and flagging logic."""
    spdx_document = {
        "spdxVersion": "SPDX-2.3",
        "SPDXID": "SPDXRef-DOCUMENT",
        "packages": [
            {"SPDXID": "SPDXRef-root", "name": "self", "versionInfo": "1.0"},
            {
                "SPDXID": "SPDXRef-a",
                "name": "left-pad",
                "versionInfo": "1.3.0",
                "licenseConcluded": "MIT",
            },
            {
                "SPDXID": "SPDXRef-b",
                "name": "readline",
                "versionInfo": "8.2",
                "licenseDeclared": "GPL-3.0-or-later",
            },
        ],
        "relationships": [
            {"relationshipType": "DESCRIBES", "relatedSpdxElement": "SPDXRef-root"},
        ],
    }
    sbom_components = parse_spdx_sbom(spdx_document)
    assert [sbom_component.component_name for sbom_component in sbom_components] == [
        "left-pad",
        "readline",
    ], sbom_components
    inventory_payload = build_inventory(
        [
            RepositorySbomInventory(
                repository_name="acme/app", software_components=sbom_components
            )
        ]
    )
    assert inventory_payload["summary"]["flagged_count"] == 1, inventory_payload
    assert is_flagged_license("AGPL-3.0-only")
    assert is_flagged_license("NOASSERTION")
    assert not is_flagged_license("Apache-2.0")
    inventory_markdown = render_inventory_markdown(
        inventory_payload, generated_at="test"
    )
    assert "Organization SBOM inventory" in inventory_markdown
    print("self-test passed")


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for the aggregator."""
    argument_parser = argparse.ArgumentParser(
        description="Aggregate org SBOMs into a central inventory."
    )
    argument_parser.add_argument(
        "--org", default="ContextualWisdomLab", help="GitHub organization login"
    )
    argument_parser.add_argument(
        "--output-dir",
        default="docs/sbom",
        help="Directory for inventory.json and inventory.md",
    )
    argument_parser.add_argument(
        "--repo",
        dest="repos",
        action="append",
        default=None,
        help="Explicit repo (owner/name); repeatable. Overrides org discovery.",
    )
    argument_parser.add_argument(
        "--generated-at", default="", help="Timestamp label for the markdown header"
    )
    argument_parser.add_argument(
        "--self-test", action="store_true", help="Run in-process assertions and exit"
    )
    return argument_parser


def main(argv: list[str]) -> int:  # pragma: no cover - CLI orchestration
    """CLI entry point: discover repos, collect SBOMs, write the inventory."""
    cli_args = build_arg_parser().parse_args(argv)
    if cli_args.self_test:
        self_test()
        return 0
    repository_names = (
        cli_args.repos if cli_args.repos else list_org_repos(cli_args.org)
    )
    repository_inventories = collect_inventories(repository_names)
    inventory_payload = build_inventory(repository_inventories)
    generated_at = cli_args.generated_at or "unspecified"
    inventory_markdown = render_inventory_markdown(
        inventory_payload, generated_at=generated_at
    )
    write_inventory(inventory_payload, inventory_markdown, Path(cli_args.output_dir))
    summary_payload = inventory_payload["summary"]
    print(
        f"Wrote inventory for {summary_payload['repo_count']} repos, "
        f"{summary_payload['component_count']} components, "
        f"{summary_payload['flagged_count']} flagged."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
