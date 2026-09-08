# Doctoring record: org-wide CI workflow duplication audit (2026-09-02)

- **Date:** 2026-09-02
- **Subject:** the standing user directive "GitHub Actions 파일을 최대한 통합하라" (consolidate GitHub
  Actions files as much as possible) had already yielded three genuine consolidations this session:
  `hourly-review-repair.yml` (18 per-repository callers → one matrix-based file, ADR-0021),
  `r-package-check.yml` (kaefa/nonnest2 R-CMD-check, ADR-0023, #1716), and a reusable
  `dependency-review.yml` target built to reconcile mightyETL/newsdom-api/scopeweave's diverging
  policies. A prior repo survey (referred to in this session as "the `wynkr83x1` survey") that found
  those candidates may have run with a result-count cap, so this audit re-swept the full org for any
  further duplication it might have missed.
- **Decision record:** none in `docs/adr/` — this is a negative/confirmatory finding (no new
  consolidation to decide), not an architecture decision.
- **PR:** see the PR that carries this commit.
- **Method:** enumerated all 63 non-archived, non-fork `ContextualWisdomLab` repositories via
  `gh api orgs/ContextualWisdomLab/repos --paginate`, listed every `.github/workflows/*.yml` file in
  each (255 files total, 19 repos with no `.github/workflows` directory at all), grouped by exact
  filename, and — for every filename appearing in 2+ repos — fetched and read the **full content** of
  every instance, comparing triggers, job topology, permissions, actual commands/tooling, and security
  posture. A shared filename was treated as a hypothesis to verify, never as evidence of duplication by
  itself, per the explicit caution this session already learned from the `dependency-review.yml`
  consolidation (where superficially similar files hid real severity-threshold and allowlist
  differences).

## Result: 19 filename groups checked, 1 real (trivial) duplicate found

| Filename | Repos checked | Verdict |
|---|---|---|
| `hourly-product-development.yml` | DiagramWeave, EgressWeave, OriginWeave, ThreadWeave, keyverse, noema | NOT_SAFE |
| `hourly-pr-maintenance.yml` | DiagramWeave, EgressWeave, TEPP, ThreadWeave | MIXED — DiagramWeave/ThreadWeave are a genuine duplicate |
| `hourly-product-loop.yml` | disksage, four-pillars, saju-caldav | NOT_SAFE |
| `hourly-nim-product-development.yml` | TEPP, four-pillars | NOT_SAFE |
| `dependency-review.yml` | `.github`, mightyETL, naruon, newsdom-api, scopeweave | NOT_SAFE (see note below) |
| `codeql.yml` | ContextualWisdomLab.github.io, bandscope, fast-mlsirm, keyverse, litellm-patched-proxy, mightyETL, newsdom-api, scopeweave | NOT_SAFE |
| `release.yml` | EgressWeave, ThreadWeave, bandscope, disksage, four-pillars, inkspan, newsdom-api | NOT_SAFE |
| `fuzz.yml` | clearfolio, codec-carver, contextual-orchestrator, linux-cluster-ops, scopeweave, semantic-data-portal, wardnet | NOT_SAFE |
| `tests.yml` | LineageWeave, appguardrail, newsdom-api, semantic-data-portal | NOT_SAFE |
| `ci.yml` | 26 repos (see full evidence in the workflow journal) | NOT_SAFE |
| `security-audit.yml` | aFIPC, bandscope | NOT_SAFE |
| `scorecard.yml` | litellm-patched-proxy, mightyETL | NOT_SAFE |
| `scorecard-analysis.yml` | `.github`, semantic-data-portal, wardnet | NOT_SAFE |
| `sbom.yml` | bandscope, mightyETL | NOT_SAFE |
| `publish-pypi.yml` | appguardrail, fast-mlsirm | NOT_SAFE |
| `bandit.yml` | bandscope, naruon | NOT_SAFE |
| `pr-governance.yml` | linux-cluster-ops, naruon | NOT_SAFE |
| `deploy.yml` | life-os, naruon | NOT_SAFE |
| `app-ci.yml` | gyeot, naruon | NOT_SAFE |

**Why NOT_SAFE, not just "different repo names":** every NOT_SAFE verdict above is backed by named,
quoted differences in *policy*, not cosmetics — different languages/toolchains (Rust vs Node vs Python
vs Java/Maven vs Java/Gradle), different security postures (SARIF upload present/absent,
`step-security/harden-runner` present/absent, `security-events: write` present/absent), different
trust models (OIDC trusted publishing vs secret-based PyPI auth), different thresholds (Bandit's
target directory and exclusions, Scorecard's `publish_results` toggle, a SARIF-finding suppression
step present in one file and absent in its closest sibling), and different job topology (job counts
from 1 to 7 within a single filename group). The full per-group evidence (concrete quoted lines,
action-pin SHAs, and reasoning) is preserved in this audit's workflow run journal — see Audit trail
below — and is too long to duplicate here without losing readability.

### The one genuine duplicate: `hourly-pr-maintenance.yml` in DiagramWeave and ThreadWeave

Byte-for-byte identical except the cron minute offset (`13` vs `11`, a deliberate stagger to avoid
simultaneous org-wide runs) and the wording of one explanatory comment block (same substance,
different phrasing). Same job name, same job permissions, same reusable-workflow pin
(`ContextualWisdomLab/.github/.github/workflows/pr-review-merge-scheduler.yml@3f65dbee6672b78802e7d71d49c390f3817bb03b`),
same `workflow_dispatch.inputs.dry_run` block, same concurrency group pattern, same full `with:` tuning
(`max_prs: "20"`, `stale_opencode_minutes: "60"`, `project_flow: "github-flow"`, `base_branch: "main"`,
`merge_mode: "direct_or_auto"`, `enable_auto_merge: true`, and the rest).

**Not acted on, deliberately.** These are already two ~20-30 line thin callers of a shared reusable
workflow (`pr-review-merge-scheduler.yml`) — the duplication here is in the *configuration values*
(`with:` block), not in any logic that would benefit from a further reusable-workflow layer. Wrapping
an already-thin wrapper in another reusable workflow for two files this small would be the kind of
unrequested abstraction this repo's own conventions warn against. If a third repo adopts the identical
tuning, promoting `max_prs: "20"`/`stale_opencode_minutes: "60"`/`project_flow: "github-flow"` to
`pr-review-merge-scheduler.yml`'s own input defaults (rather than requiring every caller to repeat
them) would be the right-sized fix at that point, not a new wrapper workflow now.

**TEPP and EgressWeave were checked and are genuinely NOT part of this duplicate**, despite sharing the
filename and calling the same reusable workflow: TEPP passes no `with:` block at all (runs on the
reusable workflow's own defaults — `max_prs` defaults to `"100"` vs the D/T pair's explicit `"20"`, a
5x difference in per-run scan scope; `stale_opencode_minutes` defaults to `"90"` vs `"60"`, a real
redispatch-threshold difference); EgressWeave is structurally different — two jobs instead of one, the
first calling a different reusable workflow entirely (`pr-review-fix-scheduler.yml`, autofix) and the
second running the merge scheduler with `enable_auto_merge: false` / `merge_mode: disabled` (never
merges, only rechecks) versus the D/T pair's `direct_or_auto`/`true`.

### Discrepancy found: `dependency-review.yml`'s central reusable target exists but no caller has migrated to it yet

`.github/workflows/dependency-review.yml` is already a `workflow_call` reusable target with inputs
(`fail_on_severity`, `allow_ghsas`, `continue_on_error`) and a dynamic dependency-graph-availability
probe, and its own header comment documents that it was built specifically to reconcile policy
differences found in mightyETL/newsdom-api/scopeweave's original standalone files. However, as of this
audit, **none of the four caller repos checked (mightyETL, naruon, newsdom-api, scopeweave) has
actually switched its own `dependency-review.yml` to `uses:` the central target** — each still carries
a full standalone implementation, and those standalone implementations still genuinely diverge on
severity threshold (`high` vs `moderate` vs unset), dependency-graph-unavailability handling (a static
`private == false` job split vs a dynamic curl probe vs no gating at all), presence of
`step-security/harden-runner` (naruon only), PR trigger branch scoping (naruon only restricts to
`develop`/`master`/`release/**`), and a vulnerability allowlist entry (newsdom-api only).

This session had understood from another agent's summary that this consolidation was "already merged"
(the central reusable workflow itself). That appears accurate for the central target's own creation,
but the caller-side migration (each of the four repos actually switching to `uses:` it) had not
happened as of this audit. Recorded here rather than silently assumed complete — a follow-up should
either confirm the caller migrations are tracked elsewhere and just not yet landed, or open the four
caller PRs, in each case checking that repo's `branch-protection required_status_checks` for the old
standalone job name first (the SHA-pin and check-run-rename pitfalls already documented in
`docs/adr/0023-r-cmd-check-reusable-workflow-consolidation.md` and PR #1728 apply identically here).

## Conclusion

The org's earlier consolidations (hourly-review-repair, R-CMD-check, and the dependency-review reusable
target) already captured the genuinely duplicated CI logic that existed. What remains under shared
filenames is, with one trivial exception, bespoke per-repo automation that happens to share a naming
convention — different languages, different security postures, and different product-specific policy
in nearly every case checked. Further org-wide filename-based searching is unlikely to surface more
candidates; if new duplication emerges, it will more likely come from two repos independently adopting
the *same new pattern* going forward (worth catching at PR-review time) than from an archaeological
sweep of existing files.

## Audit trail

- Workflow run `wf_9d141ecd-c03` (13 parallel agents, one per filename cluster or small bundle) — the
  full per-group evidence (quoted differing lines, action-pin SHAs) lives in that run's journal.
- `docs/adr/0021-hourly-review-repair-single-file-consolidation.md`,
  `docs/adr/0023-r-cmd-check-reusable-workflow-consolidation.md` — the prior genuine consolidations
  this audit checked against for completeness.
- `.github/workflows/dependency-review.yml` — the already-built but not-yet-adopted reusable target
  discussed above.
