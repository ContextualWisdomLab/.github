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

Blocking mechanical defects:

- **relative-link** — works on GitHub, 404 on the registry page.
- **mutable-release-link** — a published contract points at GitHub's moving
  `main`, `master`, or `develop` branch instead of a release tag or exact
  commit.
- **source-path** — a quoted module path tells the reader which file implements
  a feature instead of what they can do with it.
- **monetary-target** — a hard-coded internal deal value. The organization
  already decided this in `fast-mlsirm`'s
  `docs/doctoring/acquisition_readiness_gate.md`: commercial readiness
  verification may validate an explicitly supplied deal scenario, but product
  quality evidence must not depend on a hard-coded monetary target. Its CLI
  defaults `--contract-value-krw` to unset for that reason; a public package
  page must follow the same rule.

Advisory unless a repository opts into `--strict`:

- **internal-working-record** — `docs/superpowers`, `docs/product`,
  `docs/commercial`, `docs/planning`, `docs/doctoring`. These often hold
  internal evidence, but some repositories intentionally keep public operator
  guidance there.
- **go-to-market-vocabulary** and **requirement-map** — sales framing and
  PRD/TRD implementation tables usually are internal artifacts, but can be
  legitimate product-domain vocabulary.

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

## The gate's own first revision failed the org's SAST gate

Worth recording, because it is the same class of mistake this document warns
about. The first revision of the reusable workflow took a free-form
`build-command` string input and interpolated it directly into a `run:` block.
That is template injection — a caller could pass arbitrary shell into a
workflow running in its own repository context — and it is exactly what ADR
0023 forbids: reusable inputs are data and capability flags, not shell source.

The contract test for the fast-mlsirm reusable workflow asserts that no input
reaches a `run:` body. The same rule was not applied here, and the author did
not notice until Semgrep's `run-shell-injection` rule failed the PR.

The input is now `build: sdist | wheel | none`, validated in-shell so an
unexpected value exits loudly, and a contract test pins both the absence of
`build-command` and the absence of any `${{ inputs.* }}` inside a `run:` block.

## Staged adoption

`--allow <rule>` reports a rule without failing, so a repository mid-migration
can adopt the gate before its README is fully converted rather than landing a
red check it cannot fix in one PR.

## Reusable-workflow and release-artifact identity

The called workflow cannot use `github.workflow_sha` to retrieve its own source:
inside a reusable workflow the `github` context remains associated with the
caller. The gate therefore validates `job.workflow_repository` as
`ContextualWisdomLab/.github`, validates `job.workflow_sha` as a 40-hex commit,
and uses those two called-job fields for the central checkout. There is no
caller-SHA fallback.

The build frontend is the exact-action-pinned `astral-sh/setup-uv` with an exact
uv version; the inherited workflow performs no unhashed runtime `pip install`.
The caller checkout sets `persist-credentials: false` before any project build
backend runs. When `build` requests an sdist or wheel, a missing or empty dist
path is an error from the central gate; only the explicit `build: none` mode may
inspect a README, so a failed artifact boundary cannot silently downgrade itself.
When a dist directory contains both an sdist and wheel, all candidate metadata
descriptions must be identical or the gate fails closed. Published Markdown
links using GitHub's `blob/main`, `tree/main`, `master`, or `develop` forms are
blocking `mutable-release-link` findings; release tags and exact commits remain
valid.
