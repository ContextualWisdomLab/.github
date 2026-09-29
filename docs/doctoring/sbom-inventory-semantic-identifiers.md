# SBOM inventory semantic identifiers

## Scope and owner

`ContextualWisdomLab/.github` owns the organization-wide SBOM aggregation and commercial-license governance boundary implemented by `scripts/ci/sbom_inventory_aggregator.py`. Because its internal model is reused to aggregate dependency evidence from every managed repository, ambiguous vocabulary here has organization-wide blast radius even though the upstream SPDX and CycloneDX documents are vendor-owned contracts.

## Naming repair

The authoritative Python domain vocabulary is now semantic and multiword:

| Previous internal name | Current internal name | Meaning |
| --- | --- | --- |
| `Component` | `SbomComponent` | one dependency component extracted from an SBOM |
| `name` | `component_name` | dependency component name |
| `version` | `component_version` | dependency component version |
| `license` | `license_expression` | normalized SPDX-compatible license expression |
| `RepoInventory` | `RepositorySbomInventory` | parsed SBOM state for one repository |
| `repo` | `repository_name` | exact `owner/repository` identity |
| `components` | `software_components` | dependency components for that repository |
| `error` | `fetch_error` | bounded dependency-graph/SBOM retrieval failure |

Touched parser, renderer, subprocess, and collection locals use the same bounded-context vocabulary where ownership is unambiguous.

## Compatibility and anti-corruption boundaries

SPDX and CycloneDX mandate generic fields such as `name`, `version`, `id`, `license`, `components`, and related schema vocabulary. Those external keys remain unchanged while parsing and are translated immediately into the semantic Python model.

The generated `docs/sbom/inventory.json` contract already identifies itself as `cwl-sbom-inventory/v1`. Its existing keys, including `schema`, `summary`, `repo`, `error`, `name`, `version`, `license`, `components`, and `flagged`, remain byte-shape compatible in this repair to avoid silently breaking downstream readers outside the repository. `build_inventory` is the explicit v1 adapter from the semantic model to that legacy wire shape. Focused regression coverage requires both the new internal names and the unchanged v1 output keys.

Organization-wide code search on the exact protected base found `cwl-sbom-inventory/v1` and `flagged_licenses` consumers only in the aggregator, its committed generated inventory, and its focused tests. That evidence supports the bounded internal rename but does not justify deleting the public compatibility adapter.

## Persistence and operational impact

No database table, column, index, constraint, migration, ORM mapping, UPSERT path, lock boundary, hot partition, read/write split, GitHub permission, SBOM fetch endpoint, workflow trigger, or license policy changes. The repair changes Python-owned names and the internal model only; SPDX/CycloneDX input and `cwl-sbom-inventory/v1` output remain compatible.

## Verification

The test-first naming contract was committed before production repair and fails against the predecessor source because `SbomComponent` and `RepositorySbomInventory` do not yet exist there. The production and existing test consumers were then migrated through ordinary non-force history. The exact replacement source/test blobs were also exercised locally with the focused suite: 13 tests passed, including semantic model introspection, SPDX/CycloneDX parsing, v1 serialization compatibility, markdown rendering, file output, CLI defaults, and the built-in self-test. GitHub required checks on the final PR head remain authoritative for merge eligibility.
