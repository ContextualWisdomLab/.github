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

## Why two of the rules only advise

The first run against the three repositories that had just been corrected found
16, 1 and 2 remaining "findings" — and nearly all of them were wrong.

`contextual-orchestrator` genuinely ships `/api/v1/commercial_readiness/latest`,
`/api/v1/saleability_decisions/latest` and `/api/v1/commercial_due_diligence_rooms/latest`,
with tests named after them. `wardnet`'s crate genuinely computes commercial
readiness snapshots. `semantic-data-portal`'s single finding was the sentence
that explains PRD/TRD records are excluded. The stated exception — product
domain vocabulary is not a leak — was in the prose but not in the regex.

A gate that fires on a correct fix gets switched off the first week. So
`go-to-market-vocabulary` and `requirement-map` now report without failing, and
`--strict` promotes them for a repository that wants them enforced. The
mechanical rules still block, because they need no judgement: a relative link is
dead on the registry page, a quoted module path is plumbing, and a hard-coded
deal value is never a product feature.

The same pass found ADRs filed under `docs/planning/adrs/` being flagged by the
`docs/planning/` prefix. An architecture decision record is a public design
record wherever a repository files it, so the path check now exempts it.

Checked after the change: the live `fast_mlsirm-0.11.3.tar.gz` still reports 22
blocking findings (63 with `--strict`), the corrected fast-mlsirm README is
clean, and the three corrected READMEs pass with advisory notes only.

## The directory name cannot decide, either

A second false positive came from real data. `pg-llm-batch`'s README links
`docs/doctoring/bootstrap-dsn-precedence.md`, `cli-secret-input.md` and
`postgres-logical-restore.md` — and those are operator documentation a package
user genuinely needs, not internal working notes. That repository files
operational guidance under the same directory name this one uses for incident
records. A worker removed those links to satisfy the gate, then restored them in
the next commit because they were legitimate, which is the gate causing damage
rather than preventing it.

So `internal-working-record` advises too. Nothing is lost: a link into such a
directory that is ALSO repo-relative is still blocked, by `relative-link`, and
that is the mechanical defect — the page cannot resolve it. An absolute URL to
the same file resolves fine, and whether that audience wants it is judgement.

The pattern across both corrections: block only what is broken regardless of
context, advise on anything that needs to know what the product is.

## Staged adoption

`--allow <rule>` reports a rule without failing, so a repository mid-migration
can adopt the gate before its README is fully converted rather than landing a
red check it cannot fix in one PR.
