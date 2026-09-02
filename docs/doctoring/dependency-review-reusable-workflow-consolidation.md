# Dependency Review reusable workflow consolidation

## Decision

`argos`, `mightyETL`, `newsdom-api`, and `scopeweave` each carried an
independently hand-written `.github/workflows/dependency-review.yml` running
`actions/dependency-review-action` on pull requests. All four are replaced by
one new reusable workflow, `.github/workflows/dependency-review.yml` in this
repository, plus a thin `workflow_call` caller left in place of each
repository's own file. See
[ADR-0024](../adr/0024-dependency-review-reusable-workflow-consolidation.md).

## Field-by-field audit

Reading all four files' full bodies (not just the job name and action used)
found real, repo-specific policy differences, not accidental copy drift:

| Field | argos | mightyETL | newsdom-api | scopeweave | naruon |
| --- | --- | --- | --- | --- | --- |
| `fail-on-severity` | `moderate` | `high` | unset → action default `low` | `moderate` | `moderate` |
| `allow-ghsas` | none | none | `GHSA-69w3-r845-3855` | none | none |
| `comment-summary-in-pr` | unset | unset | unset | `on-failure` | `never` (explicit) |
| step `continue-on-error` | `true` | unset (blocking) | unset (blocking) | unset (blocking) | unset (blocking) |
| availability handling | none | static `repository.private` branch to a separate no-op job | none | dynamic `dependency-graph/compare` HTTP-status preflight: 200 → run, 403/404 → warn+skip, other → hard-fail | none |
| `harden-runner` (egress audit) | absent | absent | absent | absent | present |
| trigger | `pull_request: branches: [main, developmental]` | `pull_request` | `pull_request` | `pull_request`, `workflow_dispatch` | `pull_request: branches: [develop, master, release/**]`, `workflow_dispatch` |
| concurrency group | none | workflow+PR/ref group, cancel-in-progress | none | `dependency-review-`+PR/ref group, cancel-in-progress | `dependency-review-`+PR/ref group, cancel-in-progress |
| `actions/checkout` pin | unpinned `@v4` | not used | SHA `3d3c42e5aac5ba805825da76410c181273ba90b1` | SHA `9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0` (v7.0.0) | SHA `3d3c42e5aac5ba805825da76410c181273ba90b1` (v7.0.1) |
| `dependency-review-action` pin | unpinned `@v4` | SHA `a1d282b36b6f3519aa1f3fc636f609c47dddb294` (v5.0.0) | same SHA | same SHA | same SHA |
| `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` | unset | unset | `true` | unset | unset |

naruon was found later the same day by a peer session's fresh org-wide survey
-- missed by the original 4-repo survey this consolidation started from. See
"Addendum: naruon" below for the two real design changes it required
(`comment_summary_in_pr` becoming an input instead of a hardcoded uniform
value, and adding `harden-runner` uniformly).

Two decisions this audit drove (see ADR-0024 for the full reasoning):

1. `fail_on_severity`, `allow_ghsas`, and `continue_on_error` stay per-caller
   `workflow_call` inputs — flattening them to one shared value would
   silently loosen mightyETL's `high` gate or newsdom-api's documented GHSA
   allowlist exception.
2. scopeweave's dynamic Dependency Graph availability preflight (an actual
   API capability check) replaces mightyETL's static
   `github.event.repository.private` assumption everywhere, because the
   assumption is provably wrong in both directions (a private+GHAS repo, or
   a public+Dependency-Graph-disabled repo). argos and newsdom-api gain this
   safety net for free; they previously had none.
3. `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true` (newsdom-api's original only)
   is applied uniformly in the reusable workflow's job `env` rather than
   made an input — it opts the job's JS actions (`checkout`,
   `dependency-review-action`, present in all four originals) into GitHub's
   Node 24 actions runtime ahead of the default cutover, which is a
   forward-compatibility setting all four repositories benefit from
   identically, not a per-repo policy choice.

## Mechanism

`.github/workflows/dependency-review.yml` (this repository) takes four
`workflow_call` inputs (`fail_on_severity`, `allow_ghsas`,
`continue_on_error`, `comment_summary_in_pr`) and always runs the
harden-runner → checkout → availability-preflight → conditional
dependency-review → conditional unavailability-note sequence.
Each calling repository's own thin `.github/workflows/dependency-review.yml`
keeps that repository's original `on:` trigger block (argos keeps its
`branches: [main, developmental]` restriction — a `workflow_call` target
cannot itself be what GitHub triggers on pull_request), gains a
`concurrency` block if it lacked one, and adds one job:
`uses: ContextualWisdomLab/.github/.github/workflows/dependency-review.yml@0bcd22d8bb07650aafb0a8f116e4c2bbb8744f03`
with only that repository's non-default `with:` values.

### argos caller

```yaml
name: Dependency Review

on:
  pull_request:
    branches: [main, developmental]

concurrency:
  group: dependency-review-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  dependency-review:
    uses: ContextualWisdomLab/.github/.github/workflows/dependency-review.yml@0bcd22d8bb07650aafb0a8f116e4c2bbb8744f03
    with:
      fail_on_severity: moderate
      continue_on_error: true
```

### mightyETL caller

```yaml
name: Dependency Review

on:
  pull_request:

concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  dependency-review:
    uses: ContextualWisdomLab/.github/.github/workflows/dependency-review.yml@0bcd22d8bb07650aafb0a8f116e4c2bbb8744f03
    with:
      fail_on_severity: high
```

### newsdom-api caller

```yaml
name: dependency-review

on:
  pull_request:

concurrency:
  group: dependency-review-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  dependency-review:
    uses: ContextualWisdomLab/.github/.github/workflows/dependency-review.yml@0bcd22d8bb07650aafb0a8f116e4c2bbb8744f03
    with:
      fail_on_severity: low
      allow_ghsas: "GHSA-69w3-r845-3855"
```

### scopeweave caller

```yaml
name: Dependency Review

on:
  pull_request:
  workflow_dispatch:

concurrency:
  group: dependency-review-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  dependency-review:
    uses: ContextualWisdomLab/.github/.github/workflows/dependency-review.yml@0bcd22d8bb07650aafb0a8f116e4c2bbb8744f03
    with:
      fail_on_severity: moderate
```

scopeweave's original supported a `workflow_dispatch` trigger, but its own
job never gated on the event at the job level — it always ran, and its
"Check dependency review support" step early-exited with `supported=false`
for any non-`pull_request` event (the availability check itself needs
`github.event.pull_request.base.sha` / `.head.sha`, which only exist on a
`pull_request` event). The reusable workflow's preflight step carries this
same event-name guard internally, so the caller does not need its own
job-level `if:` to reproduce it — `workflow_dispatch` stays in the trigger
list and the job still runs, harmlessly skipping the gate exactly as the
original did.

### naruon caller

```yaml
name: Dependency Review

on:
  pull_request:
    branches:
      - develop
      - master
      - "release/**"
  workflow_dispatch:

concurrency:
  group: dependency-review-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  dependency-review:
    uses: ContextualWisdomLab/.github/.github/workflows/dependency-review.yml@<commit-sha>
    with:
      fail_on_severity: moderate
      comment_summary_in_pr: never
```

naruon's original also had a job-level `permissions:` block duplicating the
workflow-level one, and an informational "Log dependency review policy" step
that only printed the policy text and base/head refs -- neither is carried
into the caller: the job-level `permissions:` was redundant, and the log
step added no policy value beyond what `actions/dependency-review-action`
itself already reports on failure.

## Addendum: naruon (2026-09-02, later the same day)

A peer session's fresh org-wide workflow-duplication survey (63 repos, 255
workflow files) found `naruon` independently carrying its own
`dependency-review.yml` -- missed by the original 4-repo survey. Auditing it
found two real differences, not cosmetic ones:

1. **`step-security/harden-runner` (egress audit)**, absent from all four
   original callers. Not a per-repo policy choice -- a uniformly beneficial
   hardening practice already standard elsewhere in this org (e.g.
   `pr-review-autofix.yml`). Added to the reusable workflow itself as its
   first step, so every caller (the four already migrated included) gets it
   with no caller-side change required.
2. **`comment-summary-in-pr: never`**, an explicit opt-out that directly
   conflicts with the earlier decision to hardcode
   `comment-summary-in-pr: on-failure` uniformly (made when only scopeweave's
   original set the field, so hardcoding it cost no caller its own choice).
   Silently applying that hardcoded value to naruon would overturn a
   deliberate choice its original workflow made. Fixed by making
   `comment_summary_in_pr` a proper `workflow_call` input, default
   `"on-failure"` (no change for the four already-migrated callers),
   `naruon`'s caller explicitly setting `"never"`.

## Post-merge corrections (2026-09-02, same day)

Two real problems surfaced after the four caller PRs opened, both caught
before any of them merged (except argos, fixed retroactively):

**1. Mutable `@main` reference (Devin, security finding).** The original
callers referenced `uses: .../dependency-review.yml@main` — the example
above now shows the corrected pattern. A mutable branch ref means an
unreviewed change to `.github`'s `main` (or a reference-tampering attack)
runs directly against every caller's PR checks with zero review in the
calling repo. Fixed by pinning every caller to the exact commit SHA that
added the file, `0bcd22d8bb07650aafb0a8f116e4c2bbb8744f03` (unchanged since
it merged) — `argos` retroactively (a follow-up PR after its original
merge), the other three before their first merge. This is now the
documented pattern in the reusable workflow's own header comment: pin
`uses:` to a commit SHA for every caller, the same way every *action* step
inside the reusable workflow itself is already SHA-pinned.

**2. Required-status-check name collision (Devin, bug finding on
newsdom-api).** Converting a job from inline steps to `uses: <reusable
workflow>` changes the check-run name GitHub publishes, from the caller
job's own name (e.g. `dependency-review`) to a combined
`<caller job name> / <called job name>` (here,
`dependency-review / dependency-review`). `newsdom-api`'s `develop` branch
protection required a status check named literally `dependency-review` —
after conversion, that exact name is never published again, so the
required check stays pending forever and blocks every future merge.
Verified live: `argos` and `mightyETL` have no branch protection at all
(nothing to break); `scopeweave`'s required checks don't include
`dependency-review`; only `newsdom-api` was affected. Fixed by updating
`newsdom-api`'s branch protection required-status-checks list directly
(`gh api -X PATCH repos/.../branches/develop/protection/required_status_checks`),
replacing `dependency-review` with the actual published name
`dependency-review / dependency-review`. This is a general gotcha for any
future "convert a standalone job to a reusable-workflow caller" change —
check the target repo's branch protection for a required check matching the
job's *old* name before or immediately after merging the conversion.

## Verified before merge

- `python3 -c "import yaml; yaml.safe_load(open(...))"` on all five files
  (the reusable workflow and four callers).
- `actionlint` clean on all five files.
- Full `coverage run -m pytest tests` (2626 passed, 1 skipped) plus
  `interrogate` on `ContextualWisdomLab/.github`, confirming the new
  contract test and no regression elsewhere.
