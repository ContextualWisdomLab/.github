# Required-workflow path filters: trigger level is a no-go, job level is safe

**Status:** active repair evidence
**Owning repository:** `ContextualWisdomLab/.github`
**Canonical repair PR:** see `docs/org-required-workflow-rollout.md` entry below
**Protected baseline:** `main@bf5970df983dd36e3372c124778ec60857414eba`

## The question

Runner-admission pressure (queue-congestion investigation: 9,368 checks
queued organization-wide, roughly 3 in progress, queue depth roughly equal to
open-PR-count times required-workflow-count) makes it tempting to add
`paths:`/`paths-ignore:` to the `on:` trigger of a required workflow so a
docs-only PR never admits an expensive job (Strix, Semgrep, CodeQL, Trivy,
OSV, Scorecard). Whether that is safe depends on how the check actually gets
created in a target repository.

## Live re-verification (this phase, not taken on faith)

Organization ruleset `18156473` ("CWL Central required workflows"), fetched
live via `gh api orgs/ContextualWisdomLab/rulesets/18156473`:

```json
{
  "conditions": {
    "ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []},
    "repository_name": {"include": ["~ALL"], "exclude": ["noema", ".github", "IRT-bibliography-set"]}
  },
  "rules": [
    ".github/workflows/close-empty-pr.yml", ".github/workflows/opencode-review.yml",
    ".github/workflows/pr-review-merge-scheduler.yml", ".github/workflows/security-scan.yml",
    ".github/workflows/strix.yml", ".github/workflows/sast-semgrep.yml",
    ".github/workflows/noema-review.yml", ".github/workflows/codeql-pr.yml",
    ".github/workflows/scorecard-pr.yml", ".github/workflows/osv-scanner-pr.yml"
  ]
}
```

10 workflows, target `branch`. GitHub's required-workflow ruleset executes
each listed workflow **file from this repository** inside every covered
target repository's context, evaluated against that target repository's own
events. Confirmed live that the target repository's own `on:` filters (paths,
paths-ignore, branches, types) play no part in that: `bandscope`'s own
workflow directory is

```
bandit.yml build-baseline.yml ci.yml codeql.yml ossf-scorecard.yml
release.yml sbom.yml secret-scan-gate.yml security-audit.yml trivy.yml
```

— it has **no local** `codeql-pr.yml`, `strix.yml`, or `security-scan.yml` —
yet ruleset-injected runs of all three routinely execute against its PRs. A
`paths-ignore:` written into this repository's copy of those files is
therefore **inert** in `bandscope` and the 40+ other ruleset-covered repos: it
is never evaluated, because the check that fires belongs to the injected run,
not a repository-local trigger.

`ContextualWisdomLab/.github`'s own `main` branch is excluded from ruleset
`18156473` (see `repository_name.exclude` above) and instead uses **classic**
branch protection, fetched live via
`gh api repos/ContextualWisdomLab/.github/branches/main/protection`:

```
strict: true   enforce_admins: false
contexts:
  close-empty
  Detect CodeQL languages
  CodeQL compatibility analysis (actions)
  CodeQL compatibility analysis (python)
  scan-pr-queue
  dependency-review
  osv-scan
  osv-scan / osv-scan
  trivy-fs
  scorecard
  noema-review
  required-workflow-bootstrap
  coverage-evidence
  opencode-review
```

Exactly 14 named contexts. Classic branch protection blocks merge until every
named context reports a conclusion; a workflow-file `on:` filter that causes
GitHub to never queue that job at all leaves its context **Pending forever**
here, which is worse than "not required" -- it is an unmergeable PR with no
path to a passing state short of a repository-admin exemption.

Putting the two together: a `paths-ignore:` on a required workflow's trigger
is **inert in 40+ repositories and merge-breaking in `.github`**. Neither
side of that trade is acceptable, so trigger-level path filtering on a
required workflow is a **no-go**.

### The one documented exception: `strix.yml`

`strix.yml` already carried `paths-ignore:` on both its `push` and
`pull_request_target` triggers before this phase. A live run-event census
(last 100 runs per repository) shows why it is safe to *keep*, not a
precedent to *extend*:

```
.github     strix.yml : pull_request_target 93, push 5, repository_dispatch 2   (native runs)
bandscope   strix.yml : 0 native runs -- every Strix run there is ruleset-injected
```

`.github`, `noema`, and `IRT-bibliography-set` are excluded from ruleset
`18156473` (see the exclude list above), so *their* `strix.yml` runs are
genuinely native and the trigger-level filter is genuinely evaluated there --
it is a real, free saving today. In every other repository the filter is
simply never consulted, exactly as with the other required workflows. The
comments on both `paths-ignore:` blocks in `strix.yml` now say this
explicitly instead of implying the filter applies to PRs everywhere.

### The `codeql-pr.yml` matrix hazard

CodeQL's `analyze-head`/`analyze-merge` jobs derive `strategy.matrix` from a
separate `detect-languages` job's output. Run `33708209086` in `.github`
proved a job-level `if:` skip on a matrix-consuming job does **not** publish
correctly-named skipped legs when the matrix itself never resolved:

```
Detect CodeQL languages                                  completed  skipped
CodeQL compatibility analysis (${{ matrix.language }})    completed  skipped   <-- literal, unexpanded
CodeQL merge preview (${{ matrix.language }})             completed  skipped
```

The two required contexts `CodeQL compatibility analysis (actions)` and
`(python)` were never created for that run -- an unmergeable PR under
`.github`'s classic protection. Whether a job-level `if:` on `analyze-head`
specifically (whose matrix *is* resolvable, since `detect-languages` itself
is never skipped) would publish correctly is undocumented and unverified
either way, so the safe default was chosen: gate the five expensive **steps**
inside `analyze-head` instead of the job. The job still runs (~20s),
succeeds, and the check-run names are never in question because the matrix
resolved normally. `analyze-merge`'s `CodeQL merge preview (...)` context is
required nowhere, so it keeps a job-level guard -- and doubles as the future
observation point: if its skipped legs publish as `CodeQL merge preview
(actions)`/`(python)` rather than the literal template, `analyze-head` can be
flipped to a one-line job-level `if:` in a follow-up, with real evidence
behind it instead of an assumption.

### Independent, pre-existing blocker (not fixed by this repair)

Every ruleset-injected `CodeQL PR` run in every covered repository observed
during this phase is `startup_failure` with **zero check runs created**
(`bandscope` run `33707165672`, 2026-09-03T02:18:51Z, and equivalents in
`naruon`, `aFIPC`, `pg-erd-cloud`, `xtrmLLMBatchPython`). Every other
ruleset workflow in the same repositories enqueues normally. Gating CodeQL's
runner admission (this repair) saves nothing in those repositories until that
separate startup failure is fixed -- it is a higher-priority, independent
issue and is called out as an owner action, not addressed here.

## The mechanism this repair uses instead

A `changed-scope` job, inserted as the first job in
`security-scan.yml`, `sast-semgrep.yml`, `strix.yml`, `scorecard-pr.yml`, and
`osv-scanner-pr.yml` (byte-identical apart from one `if:` line -- see
`tests/test_docs_only_pr_runner_admission.py`), reads the PR's changed-file
list via `gh api repos/.../pulls/<n>/files` and publishes two boolean
outputs (`code`, `deps`). Downstream jobs add `needs: changed-scope` and AND
an output check into their existing `if:`. `codeql-pr.yml`'s
`detect-languages` job gained the same classifier as one more step, feeding
step-level guards on `analyze-head` and a job-level guard on `analyze-merge`.

This works in both contexts that trigger-level filtering could not satisfy
simultaneously:

- **Ruleset-injected repos:** the ruleset ignores `on:` filters, but it
  cannot skip a job's own `if:` evaluation -- that happens inside the run
  GitHub Actions actually executes, after admission, using that target
  repository's real PR event payload.
- **`.github` classic protection:** the job **always runs** (its own `if:`
  is event-based, not output-based) and always reports a conclusion --
  `success` when in scope, `skipped` when not -- so the named context is
  never left Pending.

The classifier fails **open**: an unreadable, empty, or truncated file list
(including one that doesn't match the PR's own `changed_files` count, which
GitHub caps at 3000 entries per page) scans everything. Every one of the five
workflows keeps at least one job with no `needs:` and no output-dependent
`if:` (the `changed-scope` job itself, `cancel-superseded-pr-runs` also
qualifying in `strix.yml`), so a fully-skipped run still concludes
`success`, not the undocumented `skipped` conclusion.

`LICENSE.*` was deliberately **not** reused from `strix.yml`'s existing
doc-pattern list: it matches `LICENSE.py`, which is executable. The
classifier's doc/image pattern list uses the explicit names `LICENSE`,
`LICENSE.txt`, `COPYING`, `COPYING.txt`, `NOTICE`, `NOTICE.txt` instead
(`.md`/`.rst` variants are already covered by the `*.md`/`*.rst` globs). No
`*.svg` (carries script), no bare `*.txt`, no `CODEOWNERS`; the match is
case-sensitive (`README.MD` scans). Every ambiguity resolves toward
scanning.

## Verification

`tests/test_docs_only_pr_runner_admission.py` is the RED-first contract:
byte-identical gate copies, an identical and safe doc-pattern line shared
with `codeql-pr.yml`'s classifier step, `runs-on: ubuntu-24.04` on every gate
job, no trigger-level `paths`/`paths-ignore` on any of the nine other
required-adjacent workflows, the `closed`-guard-plus-needs-output shape on
every gated job, `codeql-pr.yml`'s step-vs-job gating split, and the
always-admitted job in each of the five gate workflows.

Post-merge, the operational proof is a docs-only PR in one ruleset-covered
repository: `changed-scope` (and `detect-languages` for CodeQL) succeed while
`strix` / `Semgrep (multi-language SAST)` / `osv-scan` / `trivy-fs` /
`scorecard` report `skipped`, and the **run conclusion** is `success`, not
`skipped`.

## Safety boundary

This repair does not weaken any scanner's actual coverage. Every gate
defaults toward scanning on any ambiguity or read failure. The backstops
that make each skip safe are unchanged: `scheduled-security-scan.yml`
(push + weekly cron) and `scorecard-analysis.yml` (push + weekly cron) still
run full, unfiltered scans of the default branch. `secret-scan.yml` is
intentionally untouched (already diff-scoped and cheap; a leaked key in a
`README.md` is the canonical case a doc-only skip would otherwise miss).
`codeql-pr.yml`'s `detect-languages` job keeps its unconditional `if:`
because gating it would destroy the two required CodeQL contexts, per the
matrix hazard above.
