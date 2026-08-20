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
import re
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

_OWNER_LOGIN_PATTERN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}"
)
_REPOSITORY_NAME_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,100}")


@dataclass(frozen=True)
class Component:
    """A single software component discovered in a repository's SBOM."""

    name: str
    version: str
    license: str


@dataclass
class RepoInventory:
    """Parsed SBOM result for one repository."""

    repo: str
    components: list[Component] = field(default_factory=list)
    error: str | None = None


def normalize_license(value: Any) -> str:
    """Return a trimmed, upper-safe license string, defaulting to NOASSERTION."""
    if value is None:
        return NOASSERTION
    text = str(value).strip()
    if not text:
        return NOASSERTION
    return text


def is_flagged_license(license_expression: str) -> bool:
    """Return True when a license is copyleft/unknown under the policy."""
    normalized = normalize_license(license_expression)
    upper = normalized.upper()
    if upper == NOASSERTION or upper == "NONE":
        return True
    return any(marker in upper for marker in COPYLEFT_LICENSE_MARKERS)


def _spdx_license(package: dict[str, Any]) -> str:
    """Pick the most specific SPDX license field available on a package."""
    for key in ("licenseConcluded", "licenseDeclared"):
        candidate = normalize_license(package.get(key))
        if candidate != NOASSERTION:
            return candidate
    return NOASSERTION


def parse_spdx_sbom(document: dict[str, Any]) -> list[Component]:
    """Parse an SPDX document into components, skipping the root describes node."""
    packages = document.get("packages")
    if not isinstance(packages, list):
        return []
    described = _spdx_described_ids(document)
    components: list[Component] = []
    for package in packages:
        if not isinstance(package, dict):
            continue
        name = normalize_license(package.get("name"))
        if name == NOASSERTION:
            continue
        if package.get("SPDXID") in described:
            # The document's own describes target is the repo itself, not a dep.
            continue
        version = package.get("versionInfo")
        components.append(
            Component(
                name=str(name),
                version=normalize_license(version) if version else "",
                license=_spdx_license(package),
            )
        )
    return _dedupe(components)


def _spdx_described_ids(document: dict[str, Any]) -> set[str]:
    """Collect SPDXIDs the document DESCRIBES (its own root package)."""
    described: set[str] = set()
    relationships = document.get("relationships")
    if isinstance(relationships, list):
        for relationship in relationships:
            if not isinstance(relationship, dict):
                continue
            if relationship.get("relationshipType") == "DESCRIBES":
                related = relationship.get("relatedSpdxElement")
                if isinstance(related, str):
                    described.add(related)
    return described


def _cyclonedx_license(component: dict[str, Any]) -> str:
    """Extract a license expression from a CycloneDX component entry."""
    expression = component.get("licenses")
    if isinstance(expression, list):
        for entry in expression:
            if not isinstance(entry, dict):
                continue
            if "expression" in entry:
                return normalize_license(entry.get("expression"))
            license_obj = entry.get("license")
            if isinstance(license_obj, dict):
                candidate = license_obj.get("id") or license_obj.get("name")
                normalized = normalize_license(candidate)
                if normalized != NOASSERTION:
                    return normalized
    return NOASSERTION


def parse_cyclonedx_sbom(document: dict[str, Any]) -> list[Component]:
    """Parse a CycloneDX document into components."""
    raw_components = document.get("components")
    if not isinstance(raw_components, list):
        return []
    components: list[Component] = []
    for component in raw_components:
        if not isinstance(component, dict):
            continue
        name = component.get("name")
        if not name:
            continue
        version = component.get("version")
        components.append(
            Component(
                name=str(name),
                version=str(version) if version else "",
                license=_cyclonedx_license(component),
            )
        )
    return _dedupe(components)


def parse_sbom(document: dict[str, Any]) -> list[Component]:
    """Parse either an SPDX or CycloneDX document into components."""
    if "spdxVersion" in document or "SPDXID" in document:
        return parse_spdx_sbom(document)
    if document.get("bomFormat") == "CycloneDX" or "components" in document:
        return parse_cyclonedx_sbom(document)
    return []


def _dedupe(components: Iterable[Component]) -> list[Component]:
    """Return components sorted and de-duplicated by (name, version, license)."""
    unique = {(c.name, c.version, c.license): c for c in components}
    return sorted(unique.values(), key=lambda c: (c.name.lower(), c.version))


def build_inventory(repo_inventories: Sequence[RepoInventory]) -> dict[str, Any]:
    """Build the consolidated inventory + license roll-up from per-repo results."""
    repos_payload: list[dict[str, Any]] = []
    license_totals: dict[str, int] = {}
    flagged: list[dict[str, str]] = []
    total_components = 0
    error_count = 0

    for repo_inventory in sorted(repo_inventories, key=lambda r: r.repo.lower()):
        error_count += int(repo_inventory.error is not None)
        components_payload = [
            {
                "name": component.name,
                "version": component.version,
                "license": component.license,
                "flagged": is_flagged_license(component.license),
            }
            for component in repo_inventory.components
        ]
        total_components += len(components_payload)
        for component in repo_inventory.components:
            license_key = normalize_license(component.license)
            license_totals[license_key] = license_totals.get(license_key, 0) + 1
            if is_flagged_license(license_key):
                flagged.append(
                    {
                        "repo": repo_inventory.repo,
                        "name": component.name,
                        "version": component.version,
                        "license": license_key,
                    }
                )
        repos_payload.append(
            {
                "repo": repo_inventory.repo,
                "error": repo_inventory.error,
                "component_count": len(components_payload),
                "components": components_payload,
            }
        )

    flagged.sort(key=lambda item: (item["repo"].lower(), item["name"].lower()))
    return {
        "schema": "cwl-sbom-inventory/v1",
        "summary": {
            "repo_count": len(repos_payload),
            "component_count": total_components,
            "flagged_count": len(flagged),
            "error_count": error_count,
            "complete": error_count == 0,
            "policy": "commercial-license-only",
        },
        "license_totals": dict(sorted(license_totals.items())),
        "flagged_licenses": flagged,
        "repos": repos_payload,
    }


def _markdown_text(value: Any) -> str:
    """Return untrusted inventory text without active Markdown structure."""
    text = str(value).replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    replacements = {
        "&": "&amp;",
        "\\": "&#92;",
        "|": "&#124;",
        "<": "&lt;",
        ">": "&gt;",
        "[": "&#91;",
        "]": "&#93;",
        "`": "&#96;",
        "*": "&#42;",
        "_": "&#95;",
        "~": "&#126;",
        ":": "&#58;",
        "@": "&#64;",
        "#": "&#35;",
        ".": "&#46;",
    }
    return "".join(replacements.get(character, character) for character in text)


def render_inventory_markdown(inventory: dict[str, Any], *, generated_at: str) -> str:
    """Render the consolidated inventory as a governance-facing markdown page."""
    summary = inventory["summary"]
    lines: list[str] = [
        "# Organization SBOM inventory",
        "",
        f"Generated: {_markdown_text(generated_at)}",
        "",
        "One central view of every managed repository's software components,",
        "versions, and licenses. Feeds license and vulnerability governance",
        "alongside the central Security Scan.",
        "",
        "## Summary",
        "",
        f"- Repositories: {summary['repo_count']}",
        f"- Components: {summary['component_count']}",
        f"- Policy: {summary['policy']}",
        f"- Flagged licenses: {summary['flagged_count']}",
        f"- SBOMs unavailable: {summary['error_count']}",
        f"- Evidence completeness: {'complete' if summary['complete'] else 'incomplete'}",
        "",
        "## License roll-up",
        "",
        "| License | Components |",
        "| --- | ---: |",
    ]
    for license_key, count in inventory["license_totals"].items():
        flag = " ⚠️" if is_flagged_license(license_key) else ""
        lines.append(f"| {_markdown_text(license_key)}{flag} | {count} |")

    lines.extend(["", "## Flagged components (policy violations)", ""])
    if inventory["flagged_licenses"]:
        lines.extend(
            [
                "| Repository | Component | Version | License |",
                "| --- | --- | --- | --- |",
            ]
        )
        for item in inventory["flagged_licenses"]:
            lines.append(
                f"| {_markdown_text(item['repo'])} | {_markdown_text(item['name'])} | "
                f"{_markdown_text(item['version'] or '—')} | "
                f"{_markdown_text(item['license'])} |"
            )
    else:
        lines.append("No copyleft or NOASSERTION components detected.")

    lines.extend(["", "## Per-repository components", ""])
    for repo in inventory["repos"]:
        lines.append(f"### {_markdown_text(repo['repo'])}")
        lines.append("")
        if repo["error"] is not None:
            lines.append(f"SBOM unavailable: {_markdown_text(repo['error'])}")
            lines.append("")
            continue
        if not repo["components"]:
            lines.append("No components reported.")
            lines.append("")
            continue
        lines.extend(
            ["| Component | Version | License | Flagged |", "| --- | --- | --- | --- |"]
        )
        for component in repo["components"]:
            flag = "yes" if component["flagged"] else "no"
            lines.append(
                f"| {_markdown_text(component['name'])} | "
                f"{_markdown_text(component['version'] or '—')} | "
                f"{_markdown_text(component['license'])} | {flag} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _resolve_output_dir(output_dir: Path, *, base_dir: Path | None = None) -> Path:
    """Resolve an output directory while preventing writes outside the workspace."""
    base = (base_dir or Path.cwd()).resolve()
    resolved = (base / output_dir if not output_dir.is_absolute() else output_dir).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError("output directory must stay within the workspace") from exc
    return resolved


def write_inventory(
    inventory: dict[str, Any],
    markdown: str,
    output_dir: Path,
    *,
    base_dir: Path | None = None,
) -> None:
    """Write inventory artifacts only inside the configured workspace."""
    safe_output_dir = _resolve_output_dir(output_dir, base_dir=base_dir)
    safe_output_dir.mkdir(parents=True, exist_ok=True)
    (safe_output_dir / "inventory.json").write_text(
        json.dumps(inventory, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    (safe_output_dir / "inventory.md").write_text(markdown, encoding="utf-8")


def _run(args: Sequence[str]) -> str:  # pragma: no cover - thin subprocess wrapper
    """Run a command and return stdout, raising on failure."""
    process = subprocess.run(list(args), capture_output=True, text=True, check=True)
    return process.stdout


def _validate_owner_login(value: str) -> str:
    """Return a canonical GitHub owner login or reject an unsafe operand."""
    if not isinstance(value, str) or _OWNER_LOGIN_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid GitHub organization login")
    return value


def _validate_repo_full_name(value: str) -> str:
    """Return a canonical ``owner/repository`` name or reject it."""
    if not isinstance(value, str) or value.count("/") != 1:
        raise ValueError("invalid GitHub repository full name")
    owner, repository = value.split("/", 1)
    if (
        _OWNER_LOGIN_PATTERN.fullmatch(owner) is None
        or _REPOSITORY_NAME_PATTERN.fullmatch(repository) is None
        or repository in {".", ".."}
        or repository.startswith("-")
    ):
        raise ValueError("invalid GitHub repository full name")
    return value


def list_org_repos(org: str) -> list[str]:  # pragma: no cover - network
    """List non-archived repositories for an organization via gh."""
    validated_org = _validate_owner_login(org)
    raw = _run(
        [
            "gh",
            "repo",
            "list",
            "--no-archived",
            "--limit",
            "500",
            "--json",
            "nameWithOwner",
            "--",
            validated_org,
        ]
    )
    return [
        _validate_repo_full_name(entry["nameWithOwner"])
        for entry in json.loads(raw or "[]")
    ]


def fetch_repo_sbom(repo: str) -> RepoInventory:  # pragma: no cover - network
    """Fetch and parse one repository's dependency-graph SBOM via gh."""
    repo = _validate_repo_full_name(repo)
    try:
        raw = _run(["gh", "api", f"/repos/{repo}/dependency-graph/sbom"])
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip().splitlines()
        return RepoInventory(
            repo=repo, error=detail[-1] if detail else "sbom unavailable"
        )
    payload = json.loads(raw or "{}")
    document = payload.get("sbom", payload)
    return RepoInventory(repo=repo, components=parse_sbom(document))


def collect_inventories(
    repos: Sequence[str],
) -> list[RepoInventory]:  # pragma: no cover - network
    """Fetch every repository's SBOM into per-repo inventories."""
    if len(repos) <= 1:
        return [fetch_repo_sbom(repo) for repo in repos]

    max_workers = min(SBOM_FETCH_WORKERS, len(repos))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Keep original order by using map and converting to list
        return list(executor.map(fetch_repo_sbom, repos))


def self_test() -> None:
    """Run in-process assertions covering parse, roll-up, and flagging logic."""
    spdx = {
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
    components = parse_spdx_sbom(spdx)
    assert [c.name for c in components] == ["left-pad", "readline"], components
    inventory = build_inventory([RepoInventory(repo="acme/app", components=components)])
    assert inventory["summary"]["flagged_count"] == 1, inventory
    assert is_flagged_license("AGPL-3.0-only")
    assert is_flagged_license("NOASSERTION")
    assert not is_flagged_license("Apache-2.0")
    markdown = render_inventory_markdown(inventory, generated_at="test")
    assert "Organization SBOM inventory" in markdown
    print("self-test passed")


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for the aggregator."""
    parser = argparse.ArgumentParser(
        description="Aggregate org SBOMs into a central inventory."
    )
    parser.add_argument(
        "--org", default="ContextualWisdomLab", help="GitHub organization login"
    )
    parser.add_argument(
        "--output-dir",
        default="docs/sbom",
        help="Directory for inventory.json and inventory.md",
    )
    parser.add_argument(
        "--repo",
        dest="repos",
        action="append",
        default=None,
        help="Explicit repo (owner/name); repeatable. Overrides org discovery.",
    )
    parser.add_argument(
        "--generated-at", default="", help="Timestamp label for the markdown header"
    )
    parser.add_argument(
        "--self-test", action="store_true", help="Run in-process assertions and exit"
    )
    return parser


def main(argv: list[str]) -> int:  # pragma: no cover - CLI orchestration
    """CLI entry point: discover repos, collect SBOMs, write the inventory."""
    args = build_arg_parser().parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    repos = (
        [_validate_repo_full_name(repo) for repo in args.repos]
        if args.repos
        else list_org_repos(args.org)
    )
    inventories = collect_inventories(repos)
    inventory = build_inventory(inventories)
    generated_at = args.generated_at or "unspecified"
    markdown = render_inventory_markdown(inventory, generated_at=generated_at)
    write_inventory(inventory, markdown, Path(args.output_dir))
    summary = inventory["summary"]
    print(
        f"Wrote inventory for {summary['repo_count']} repos, "
        f"{summary['component_count']} components, "
        f"{summary['flagged_count']} flagged."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
