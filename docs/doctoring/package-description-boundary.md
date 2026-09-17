# The package description is not the repository README

Date: 2026-09-18

## The finding

`fast-mlsirm` 0.11.3's published PyPI description carried a `## Commercial
Readiness` section: an enterprise sales gate, a KRW 2,000,000,000 product gate,
buyer packet and procurement due-diligence links, and a transcript of the
internal evidence pipeline. Checking the live artifact rather than the README on
disk found 68 boundary findings in `fast_mlsirm-0.11.3.tar.gz`, including 16
repo-relative links that are 404s on the registry page because only `LICENSE`
and the package sources ship in the distribution.

Two other live packages were checked the same way: `threadweave` 0.1.0 and
`rankweave` 0.1.0 each carry 3 dead links, one of them pointing at a source
module path. `appguardrail` and `egressweave` carry dead links but no
vocabulary leak.

## Why a README check is not enough

The registry renders the description recorded in the built artifact — PKG-INFO
for an sdist, METADATA for a wheel — not the file in the repository. Those can
differ: a release is built from a commit, and packaging config decides what is
included. `scripts/ci/package_description_boundary.py` therefore reads the
built artifact and falls back to the README only for a repository that has not
released yet.

## What is and is not a finding

A repository README may link internal design records; that is public
development history and the organization publishes it deliberately. The same
text on a registry page is different, because only the distribution's files
exist there and the reader is installing rather than developing.

Blocking:

- **relative-link** — works on GitHub, 404 on the registry page.
- **internal-working-record** — `docs/superpowers`, `docs/product`,
  `docs/commercial`, `docs/planning`, `docs/doctoring`. Internal evidence, and
  not shipped.
- **source-path** — a quoted module path tells the reader which file implements
  a feature instead of what they can do with it.
- **monetary-target** — a hard-coded internal deal value. The organization
  already decided this in `fast-mlsirm`'s
  `docs/doctoring/acquisition_readiness_gate.md`: commercial readiness
  verification may validate an explicitly supplied deal scenario, but product
  quality evidence must not depend on a hard-coded monetary target. Its CLI
  defaults `--contract-value-krw` to unset for that reason; a public package
  page must follow the same rule.
- **go-to-market-vocabulary** and **requirement-map** — sales framing and
  PRD/TRD implementation tables are internal artifacts.

Deliberately not a finding:

- **`docs/adr` links.** A public architecture decision record is legitimate to
  advertise. It only has to be an absolute URL.
- **Product vocabulary that happens to look commercial.** `appguardrail` ships
  a real `buyer-diligence` CLI subcommand and `scopeweave` really does check
  procurement packages. Those belong in their documentation. The rule targets
  internal framing, not a product's domain.

## Staged adoption

`--allow <rule>` reports a rule without failing, so a repository mid-migration
can adopt the gate before its README is fully converted rather than landing a
red check it cannot fix in one PR.
