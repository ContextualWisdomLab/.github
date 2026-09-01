# Hourly commercial-license SBOM remediation

Status: implementation evidence for the central ContextualWisdomLab supply-chain control plane.  
Scope: live repositories whose GitHub metadata proves `fork=false`; forks are provenance evidence only and are never owner-side remediation targets.

## Observed gap

At `ContextualWisdomLab/.github@5f81d8e665b7d3f51f379a090e077486dbf548c5`, the central SBOM inventory still reports `pending first scheduled run`, zero repositories, and zero components. The scheduler runs only once a week and delegates organization discovery to an aggregator that does not itself exclude forks on protected `main`. That combination can make a zero-finding report look materially cleaner than the evidence actually supports.

The existing license classifier is intentionally high-recall but is not a legal conclusion: it substring-flags GPL/AGPL/LGPL/MPL/EPL/CDDL and related expressions plus `NOASSERTION`. A flagged component therefore means **commercial-policy review is required**, not “commercial use is forbidden.” The GNU GPL explicitly permits selling copies; obligations depend on how covered code is combined, modified, conveyed, or offered as a network service. AGPLv3 adds a corresponding-source obligation for users interacting remotely with a modified covered program under section 13.

## Decision

1. Refresh the organization inventory every hour.
2. Build the owned target set from live GitHub repository metadata and admit only entries with `isFork == false` before any SBOM collection.
3. Require an organization-wide SBOM credential before discovery or collection. The repository-scoped `github.token` is not an acceptable fallback because it can silently hide private sibling repositories; absence of the dedicated token or successful OpenCode app exchange fails closed instead of publishing a partial inventory.
4. Reconcile SPDX/CycloneDX evidence with manifests, lockfiles, vendored/native/binary assets, container inputs, generated packages, and dependency-graph evidence before calling an inventory complete.
5. Interpret license expressions as evidence requiring an explicit `allow`, `review`, or `replace/block` outcome tied to the actual product distribution and hosted-service model. Do not equate copyleft with non-commercial use.
6. For an actionable incompatibility, remediate in this order: remove an unused component; replace it with a maintained permissively licensed equivalent; implement only the bounded required capability cleanly in-house from independent product/API/standards behavior; isolate it behind an independently deployed service/process boundary only when that genuinely changes the technical and legal coupling; or redesign the feature to remove the dependency.
7. A replacement implementation must not copy protected source, tests, comments, data, expressive structure, or other copyrightable material from the incompatible implementation. Product contracts, published standards, independent interoperability documentation, and lawful black-box behavior are the acceptable specification sources.
8. Update manifests and lockfiles, SBOMs, NOTICE/THIRD_PARTY_NOTICES, tests, architecture/ADR evidence, CHANGELOG when release-relevant, and `docs/product-technical-gap-baseline.md`; then rerun exact-head Checks/reviews and merge only through ordinary branch protection.
9. Preserve concurrent writers. The recurring inventory publication branch must advance without history rewriting; a race fails closed and is retried on a later run. Because checkout deliberately keeps `persist-credentials: false`, publication establishes Git authentication through the masked organization-wide `GH_TOKEN` with `gh auth setup-git` before the first remote Git operation.

## Standards and interpretation baseline

- SPDX 3.0 is the current SPDX document specification; SPDX is standardized as ISO/IEC 5962:2021. SBOM license identifiers and expressions are machine contracts and must not be reduced to free-text substring heuristics for final policy decisions.
- CycloneDX 1.7 is the current stable BOM specification and ECMA-424 2nd Edition. CycloneDX 2.0 is announced for 2026 but is not yet the stable baseline as of 2026-09-01.
- GPL-family software can be used commercially. The engineering concern for ContextualWisdomLab is whether the concrete incorporation, modification, conveyance, hosted-service behavior, source-offer obligation, attribution, patent terms, or reciprocal scope conflicts with the intended proprietary/commercial product contract.
- Unknown (`NOASSERTION`/unlicensed) and explicitly non-commercial, evaluation-only, field-of-use, or source-available restrictions fail closed into review until provenance and rights are established.

This is an engineering governance policy and evidence record, not legal advice. Ambiguous rights or license compatibility that cannot be resolved from authoritative terms remains a legal-rights blocker rather than being guessed by automation.

## Verification contract

The scheduler contract is executable in `tests/test_sbom_inventory_scheduler_contract.py`: it binds assertions to the named executable discovery, aggregation, credential, and publication steps; requires an hourly cron; requires live `isFork == false` filtering; passes only the verified repositories explicitly to the aggregator; rejects `github.token` fallback; configures authenticated Git before remote publication; and prohibits force-push behavior. The first inventory run after merge is not considered complete merely because it reports zero findings; unavailable SBOMs and incomplete dependency materialization remain explicit defects to repair.

## References

Free Software Foundation. (n.d.). *Frequently asked questions about the GNU licenses*. https://www.gnu.org/licenses/gpl-faq.html

Free Software Foundation. (2007). *GNU Affero General Public License, version 3*. https://www.gnu.org/licenses/agpl-3.0.html

OWASP Foundation. (2025). *CycloneDX specification 1.7 (ECMA-424, 2nd ed.)*. https://cyclonedx.org/specification/overview/

SPDX Workgroup. (n.d.). *SPDX specifications*. Linux Foundation. https://spdx.dev/use/specifications/
