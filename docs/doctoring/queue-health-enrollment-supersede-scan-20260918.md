# Queue-health enrollment + automation PR supersede scan (2026-09-18)

GraphQL-first triage of open ContextualWisdomLab/.github enrollment drafts and automation PRs `#2166` / `#2170`–`#2175`. Three-dot diffs vs `origin/main`; supersession verified by `git grep -lF` content on the tree (not ancestry). No force-push; no merges.

## Closed as superseded

| PR | Target enrollment | Successor | Evidence comment |
| --- | --- | --- | --- |
| [#2196](https://github.com/ContextualWisdomLab/.github/pull/2196) | `ContextualWisdomLab/disksage` | [#2241](https://github.com/ContextualWisdomLab/.github/pull/2241) | [comment](https://github.com/ContextualWisdomLab/.github/pull/2196#issuecomment-5720692404) |
| [#2200](https://github.com/ContextualWisdomLab/.github/pull/2200) | `ContextualWisdomLab/LineageWeave` | [#2241](https://github.com/ContextualWisdomLab/.github/pull/2241) | [comment](https://github.com/ContextualWisdomLab/.github/pull/2200#issuecomment-5720693258) |
| [#2202](https://github.com/ContextualWisdomLab/.github/pull/2202) | `ContextualWisdomLab/noema` | [#2241](https://github.com/ContextualWisdomLab/.github/pull/2241) | [comment](https://github.com/ContextualWisdomLab/.github/pull/2202#issuecomment-5720694142) |
| [#2204](https://github.com/ContextualWisdomLab/.github/pull/2204) | `ContextualWisdomLab/quarantine-sandbox-runtime` | [#2241](https://github.com/ContextualWisdomLab/.github/pull/2241) | [comment](https://github.com/ContextualWisdomLab/.github/pull/2204#issuecomment-5720695079) |
| [#2211](https://github.com/ContextualWisdomLab/.github/pull/2211) | `ContextualWisdomLab/OriginWeave` | [#2241](https://github.com/ContextualWisdomLab/.github/pull/2241) | [comment](https://github.com/ContextualWisdomLab/.github/pull/2211#issuecomment-5720696048) |
| [#2212](https://github.com/ContextualWisdomLab/.github/pull/2212) | `ContextualWisdomLab/mhtml-etl-gateway` | [#2243](https://github.com/ContextualWisdomLab/.github/pull/2243) | [comment](https://github.com/ContextualWisdomLab/.github/pull/2212#issuecomment-5720696927) |

All six strings are present on `origin/main` in both `config/actions_queue_health_repositories.json` and `tests/test_actions_queue_health_contract.py`. Three-dot diffs remained non-empty only because branches forked from a pre-enrollment allowlist tip.

## Kept open (unique residual delta)

| PR | Residual (one-liner) |
| --- | --- |
| [#2166](https://github.com/ContextualWisdomLab/.github/pull/2166) | Product-performance attestation workflows/scripts/tests (~2.9k LOC) absent from `main`. |
| [#2170](https://github.com/ContextualWisdomLab/.github/pull/2170) | `RCA_SOURCE_BACKED_PRE_REVIEW_CHECKS` routes Required OpenCode `coverage-evidence` failures into RCA (not on `main`). |
| [#2171](https://github.com/ContextualWisdomLab/.github/pull/2171) | Unique: `sanitize_line` early-exit for `:`/`=`/`://`; three-dot also carries large stale deletions — needs rebase before any merge. |
| [#2173](https://github.com/ContextualWisdomLab/.github/pull/2173) | New `agent-source-fix.yml` bounded command lane + contract (absent from `main`). |
| [#2174](https://github.com/ContextualWisdomLab/.github/pull/2174) | New `agent_source_repair.py` + repair workflows/sweep (absent from `main`). |
| [#2175](https://github.com/ContextualWisdomLab/.github/pull/2175) | Alternate source-fix router/dispatch/worker stack (absent from `main`; overlaps `#2173`/`#2174` conceptually). |

## Out of scope / already settled

- `#2172` already **MERGED** (not open).
- Other open PRs in ~`#2196`–`#2220` (`#2205`, `#2207`, `#2209`, `#2215`) are not queue-health enrollment drafts; left untouched.
- `#1857` matched a loose enrollment search but is OriginWeave browser evidence, not this series.

## Cache

Allowlist on `origin/main` at scan time: `.github`, ConceptWeave, ELUNVERA, LineageWeave, OriginWeave, TEPP, contextual-orchestrator, disksage, fast-mlsirm, mhtml-etl-gateway, naruon, noema, pg-llm-batch, quarantine-sandbox-runtime.
