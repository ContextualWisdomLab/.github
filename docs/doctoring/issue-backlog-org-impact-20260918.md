# Issue backlog — org CI / review / security impact (2026-09-18)

Triage snapshot for open ContextualWisdomLab/.github issues that affect
organization Actions capacity, required workflows, review/merge schedulers, or
security gates. GraphQL caches live under `/tmp/issue-backlog-*.json` on the
triage host (not committed). This file is the durable ranked backlog for the
lead READY queue; large implementations stay out of this pass.

## Method

| Source | Cache | Notes |
| --- | --- | --- |
| `.github` open issues (183) | `/tmp/issue-backlog-dot-github-all.json` | GraphQL `issues(states:OPEN)`, 2 pages |
| Linked PR timeline (priority set) | `/tmp/issue-backlog-linked.json` | `CrossReferencedEvent` + `closedByPullRequestsReferences` |
| Open `.github` PRs (sample 100) | `/tmp/issue-backlog-open-prs.json` | title/body `#N` / Fixes mapping |
| Project #1 (first 100 items) | `/tmp/issue-backlog-project1.json` | mostly historical Done; open decisions `#365`/`#366` |

Ranking prefers **org-wide merge blockage** and **false required-gate failure**
over backlog hygiene. Impact tags: `capacity` · `security` · `correctness` · `DX`.

## Top 10 — ranked next actions

| Rank | Issue | Org impact | PR covering? | Next action | READY note for lead |
| --- | --- | --- | --- | --- | --- |
| 1 | [#2248](https://github.com/ContextualWisdomLab/.github/issues/2248) `sast-semgrep: false-positive dynamic-urllib-use-detected now blocks every PR` | correctness · capacity | No open PR | **implement** | Suppress/prove FP on contract-test urllib; restore Semgrep as a real Medium+ gate without org-wide red |
| 2 | [#2208](https://github.com/ContextualWisdomLab/.github/issues/2208) `codeql: repaired SARIF gate blocks every PR on URL-sanitization FP in contract test` | correctness · capacity | Mentions open `#2191` / `#2209` (not closing) | **implement** | Same class as #2248 for CodeQL dispatch; fix test or narrow rule before capacity recovers |
| 3 | [#2141](https://github.com/ContextualWisdomLab/.github/issues/2141) `CodeQL dispatch reports clean scan as failure when only wake step failed` | correctness · DX | Mentions `#2137` open | **implement** | Verdict must read SARIF/gate evidence, not wake-job conclusion |
| 4 | [#2165](https://github.com/ContextualWisdomLab/.github/issues/2165) `noema-review fails closed on provider 502/429 after failover` | capacity · correctness | Merged CO/sidecar refs; residual open | **implement** | Distinguish transport exhaustion from product risk; avoid blocking unchanged consumer heads |
| 5 | [#2148](https://github.com/ContextualWisdomLab/.github/issues/2148) `Private-target review pool is three OpenRouter free ZDR routes; 429 burst fails closed` | capacity · security | Merged ZDR feed work; pool still thin | **needs-owner** | Owner decision on ZDR pool diversification vs fail-closed availability (ADR-0003 risk still open) |
| 6 | [#2139](https://github.com/ContextualWisdomLab/.github/issues/2139) `Unbounded review runner occupancy after implicit 90s timeout removal` | capacity | Mentions `#2137`/`#2140` open | **implement** | Admission/continuation bound only — do **not** reintroduce model-path wall timeouts (product-goal §8) |
| 7 | [#2045](https://github.com/ContextualWisdomLab/.github/issues/2045) `materialize exact-head review jobs after Ready transition` | correctness | No closing PR | **implement** | Draft→Ready must mint authenticated current-head OpenCode/Noema evidence |
| 8 | [#2000](https://github.com/ContextualWisdomLab/.github/issues/2000) `Strix cancelled at 6h with no verdict (909 attempts, no exhaustion event)` | capacity · correctness | No closing PR | **implement** | Emit exhaustion/verdict before Actions hard ceiling; bind request identity in evidence |
| 9 | [#2055](https://github.com/ContextualWisdomLab/.github/issues/2055) `[security-scan] diff-scoped skip leaves classic required contexts blocked` | correctness · capacity | **Open [#2072](https://github.com/ContextualWisdomLab/.github/pull/2072)** (`willCloseTarget`) | **implement** | Land/re-review `#2072`; classic branch-protection contexts must conclude success, not Pending |
| 10 | [#1531](https://github.com/ContextualWisdomLab/.github/issues/1531) / sibling [#712](https://github.com/ContextualWisdomLab/.github/issues/712) Actions queue saturation / starvation | capacity | Partial: `#1656`/`#1798`/`#1938` merged; `#1930` open | **needs-owner** | Ongoing capacity program; do not close until measured queue + merge throughput recovered |

### Immediate follow-ons (outside top 10 but READY)

| Issue | Impact | PR? | Action |
| --- | --- | --- | --- |
| [#1942](https://github.com/ContextualWisdomLab/.github/issues/1942) Strix blocks on missing `path:line` | security · correctness | **Open [#2089](https://github.com/ContextualWisdomLab/.github/pull/2089)** | Finish PR |
| [#2082](https://github.com/ContextualWisdomLab/.github/issues/2082) zero-diff auto-close drops valid delta | correctness | **Open [#2090](https://github.com/ContextualWisdomLab/.github/pull/2090)** | Finish PR |
| [#2169](https://github.com/ContextualWisdomLab/.github/issues/2169) autofix RCA for coverage-evidence failures | DX · capacity | **Open [#2170](https://github.com/ContextualWisdomLab/.github/pull/2170)** | Finish PR |
| [#1917](https://github.com/ContextualWisdomLab/.github/issues/1917) stale `cancel-in-progress: false` comment vs `:26 true` | DX · correctness | None | **implement** (one-file comment) — workflow-level concurrency is `true`; comment still claims bootstrap `false` |
| [#810](https://github.com/ContextualWisdomLab/.github/issues/810) dependency-review unavailability | security | Fail-open fixed via `#897`; public `403` remains | **needs-owner** — GitHub dependency-graph entitlement / evidence, not reopen fail-open |
| [#1929](https://github.com/ContextualWisdomLab/.github/issues/1929) CodeQL dispatch terminal status unproven | correctness | `#1774` merged; still open | **implement** — prove cross-repo publication |
| [#1931](https://github.com/ContextualWisdomLab/.github/issues/1931) queue delay invalidates `base_sha` dispatch | capacity · correctness | `#1932`/`#1937`/`#1939` merged | Re-measure; close only if live failure rate gone |
| [#1800](https://github.com/ContextualWisdomLab/.github/issues/1800) concurrency epic | capacity | `#1958` merged | Keep open as epic until Noema/Strix/OpenCode share exact-PR contract |
| [#1759](https://github.com/ContextualWisdomLab/.github/issues/1759) migrate to released `orchestrator/free` | security · DX | Sidecar on free; no CO Release yet | **needs-owner** — release + consumer cutover |
| [#624](https://github.com/ContextualWisdomLab/.github/issues/624) leave GitHub Models before 2026-07-30 | capacity · security | Partial (`#668`); `opencode.jsonc` still mentions github-models | **implement** — finish pool cutover / close residual GH Models path |
| [#772](https://github.com/ContextualWisdomLab/.github/issues/772) solo-maintainer review policy | DX · security | Open mentions | **needs-owner** — identity/bypass policy without gate weakening |
| [#1340](https://github.com/ContextualWisdomLab/.github/issues/1340) remove admin merge bypass | security | Open mentions | **needs-owner** |
| Project [#365](https://github.com/ContextualWisdomLab/.github/issues/365) / [#366](https://github.com/ContextualWisdomLab/.github/issues/366) | security | Todo on Project #1 | **needs-owner** decisions |

## Closable with evidence (count: **5**)

These remain **OPEN** on GitHub but the unique valid delta is on protected `main`.
Triage comments with evidence links were posted in this pass; lead may close after
spot-check.

| Issue | Evidence on `main` | Merged PR | Doctoring / code pin |
| --- | --- | --- | --- |
| [#2120](https://github.com/ContextualWisdomLab/.github/issues/2120) scheduler statuses permission | `statuses: read` on scan job | [#2121](https://github.com/ContextualWisdomLab/.github/pull/2121) (2026-09-13) | `docs/doctoring/scheduler-status-read-permission.md` |
| [#2116](https://github.com/ContextualWisdomLab/.github/issues/2116) HWPX UTF-8 block | Pingora admits bounded `.hwpx` | [#2144](https://github.com/ContextualWisdomLab/.github/pull/2144) (2026-09-13) | `docs/doctoring/pingora-hwpx-evidence-admission.md` |
| [#2159](https://github.com/ContextualWisdomLab/.github/issues/2159) Strix PR-delta binding | `strix_evidence_binding.py` | [#2235](https://github.com/ContextualWisdomLab/.github/pull/2235) (2026-09-17) | `docs/doctoring/strix-evidence-binding-2159-2168.md` |
| [#2168](https://github.com/ContextualWisdomLab/.github/issues/2168) false “already applied” remediation | same binder + remediation states | [#2235](https://github.com/ContextualWisdomLab/.github/pull/2235) | same doctoring record |
| [#1935](https://github.com/ContextualWisdomLab/.github/issues/1935) pre-review update discards in-flight checks | hold while checks queued/running | [#1937](https://github.com/ContextualWisdomLab/.github/pull/1937) (2026-09-05) | `scripts/ci/pr_review_merge_scheduler_core.py` + procedure doc cite `#1935` |

**Not counted as closable yet:** `#1976` (only Semgrep gate folded in `#2147`; other workflows may still double-boot scope detection), `#1800` (epic residual), `#1759` (no released gateway), `#810` (public 403 remains), `#624` (GH Models residual).

## Project #1 cross-check

`naruon Platform Roadmap` Project #1 first page is largely Done historical PRs.
Live open decisions still relevant to security gates: `.github#365` (Code Security
vs CodeQL-only ruleset), `.github#366` (Trivy SARIF severity limit). Capacity /
scheduler work is tracked primarily as `.github` issues above, not as fresh
Project cards.

## Constraints observed this pass

- No large implementation PRs; deliverable is this doctoring backlog.
- No gate weakening, force-push, or self-approve.
- Model-path timeouts remain policy-fixed (do not “fix” `#2139` with a 900s
  inference cap).
- Private-target review stays ZDR-first; `#2148` is an availability risk under
  that policy, not a license to drop ZDR.

## READY queue (lead)

1. Land false-positive gate repairs `#2248` + `#2208` (+ `#2141` verdict wiring).
2. Finish open covering PRs `#2072`, `#2089`, `#2090`, `#2170`.
3. Close the five evidence-backed issues after comment spot-check.
4. Owner thread: `#2148` ZDR pool, `#810` dependency-graph 403, `#365`/`#366`,
   `#772`/`#1340` governance identity.
5. One-file hygiene: `#1917` comment vs `cancel-in-progress: true`.
