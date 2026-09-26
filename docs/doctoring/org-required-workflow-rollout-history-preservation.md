# Organization required-workflow rollout history preservation

Status: Proposed evidence ledger
Date: 2026-09-02 KST
Canonical owner: `ContextualWisdomLab/.github`
Source snapshot preserved: `80fdc4388ea6bc94eab69c410cb957e52f5cd4f5:docs/org-required-workflow-rollout.md`

## Purpose

The current rollout document was reconciled from the historical seven-workflow incident state to the live ten-workflow contract. That reconciliation must not erase valid operational evidence merely because the current policy changed. This doctoring record preserves the superseded-but-valid incident chronology that operators and later agents may need to reconstruct why the control plane looks the way it does.

The current authority is the live ruleset plus the exact-inventory audit and its independent regression oracle. Items below are historical evidence, not permission to restore superseded behavior.

## Preserved control-plane chronology

- On 2026-06-28 20:09 KST, organization ruleset `18156473` was re-pinned to `.github@main` SHA `531482764986bf7da98c1317d59e6e51e7c61d02` for the then-current three required workflow paths.
- `ContextualWisdomLab/naruon` reported inherited active ruleset `18156473` with those three required workflow paths, establishing early target-repository inheritance.
- `ContextualWisdomLab/ContextualWisdomLab.github.io#25` merged the thin central scheduler caller and repository-local bootstrap fixes; its main Strix run `28217860369` passed.
- `ContextualWisdomLab/.github#74` changed OpenCode review model order to DeepSeek R1 first and added a catalog fallback pool.
- `ContextualWisdomLab/.github#75` removed the Strix finding against the scheduler command wrapper by using `subprocess.run(..., check=True)` while preserving the scrubbed failure contract. Main Strix run `28218982899` passed after merge.
- `ContextualWisdomLab/.github#77` merged the central OpenCode required-workflow path. Same-head OpenCode proof run `28224085121` passed coverage evidence, CodeGraph initialization, bounded evidence preparation, model review, review publication, and approval-gate publication on head `59a8da0b2f56b862f6c5a0c69885f4045d6dc732`; central Strix run `28223698075` passed on that same head.
- Ruleset `18156473` was then renamed `CWL Central required workflows` and required `.github/workflows/strix.yml` and `.github/workflows/opencode-review.yml` from `.github@main` SHA `6440d493816f8a4d66e32f2e5e8e6a9156d7f488`.
- `ContextualWisdomLab/.github#79` merged the central scheduler `pull_request_target` path and PR-scoped `--pr-number` lookup. Its second current-head proof passed coverage evidence in 10 seconds, Strix in 8m33s, and OpenCode review in 8m57s on head `17c62f3809c57ca4b1a9a63e14f325c9f2a1acdb`.
- Ruleset `18156473` subsequently required Strix, OpenCode, and the PR Review Merge Scheduler from `.github@main` SHA `807254a04efafd5f806e0f70cb067ecf050cfd11`.
- `ContextualWisdomLab/.github#85` installed target-repository `requirements.txt` before Python coverage evidence; `#88` hardened the OpenCode output normalizer; `#94` hardened Mermaid labels; `#95` blocked approvals contradicting exact changed-file evidence.
- `ContextualWisdomLab/.github#100` added required-workflow job rerun support and cancellation of older same-PR OpenCode runs before retrying current head. Local verification on `3c62c37a4deabdb0c6ed4ddf0951c1987f09866b` reported 38 pytest tests, 100% coverage, and 100% interrogate. It merged at `81408f3dbe0a3c43dc4b76133f72a5e314df8a10` on 2026-06-29 05:45 KST.
- `ContextualWisdomLab/.github#136` changed approved stale PR handling so `BEHIND` branches are updated before failed-check or `ACTION_REQUIRED` decisions disable auto-merge.
- `ContextualWisdomLab/.github#137` made the central PR Review Fix Scheduler target-repository-aware across workflow call, dispatch, schedule, and repository variables; the later central autofix worker made `.github` the default autofix owner rather than copying full workers into consumers.
- `ContextualWisdomLab/.github#138` added compare-API branch-freshness evidence; `#140` extended update-branch handling to already-auto-merge-enabled PRs; `#145` treated compare `status: behind` as freshness evidence and merged at `1ec0f3dcc7250fdf4a5a3ec6c26feaa98cce4f48`.
- A 2026-06-30 00:40 KST dry run found update-branch candidates in `ContextualWisdomLab/.github#147` and `ContextualWisdomLab/naruon#803`. `ContextualWisdomLab/.github#151` added protected-base push triggers and the `auto_merge_enabled` event, merged as `00018f7783522447a71acd08a946e3504e18ff74`, and created push-triggered scheduler run `28385177585`; that run remained queued awaiting runner assignment.
- `ContextualWisdomLab/.github#146` taught central OpenCode coverage evidence to discover nested requirements-only Python projects and merged at `0393bc1c48b80597d6d35c336aca43aee18e22b9`.
- `ContextualWisdomLab/.github#149` tightened the central model-failure path and merged at `919b83faf29237803cfdd0cfd6febbe5ae1a8a3c`. Follow-up `6fdffe43b50a2246b3db2790a0ab532618a89c2b` fixed temporary evidence-file handling. Local validation covered pytest, 100% coverage, 100% interrogate, actionlint, bash syntax, and diff checks; the full quick-gate exceeded the local 300-second environment cap and was not represented as complete evidence.
- `ContextualWisdomLab/semantic-data-portal#3` removed repository-local OpenCode, Strix, and scheduler workflows. `ContextualWisdomLab/pg-erd-cloud#361` removed its repository-local PR Review Fix Scheduler wrapper after central ownership matured and merged at `21cbc14b21d59ac28ac789de58502816cc8df6ad`.
- `ContextualWisdomLab/naruon` classic protection later stopped requiring direct `strix` or `opencode-review` contexts on `develop` while org ruleset `18156473` remained authoritative. `ContextualWisdomLab/naruon#852` moved release-governance contracts to the central scheduler model; its first central coverage run exposed the nested-requirements defect later repaired by `.github#146`.

## Preserved review/merge evolution

- `ContextualWisdomLab/.github#225` raised high reasoning effort for reasoning-capable OpenCode definitions and merged at `50c6ef82f52af3eeb0e58c174902fc9855c36682`.
- `#226` stopped previous deterministic fallback approval bodies from satisfying current-head evidence and merged at `57a1fa580731a0f76b31dcf29a597c5715dba2fd`.
- `#230` added exact changed-file candidates to merge-conflict guidance and merged at `0cab5c8d46e88c1a3f68ef3f71b5d44d971cd2ef`.
- `#232` removed the workflow-only deterministic approval fallback and merged at `f545a9917933f8f81a76ea0044cbce0aae1ac5bd`.
- `#233` blocked false trivial approval reasons for material workflow/source/test changes and merged at `4ff660c8396b78a1b82aef8c316b26527864d450`.
- `#234` repaired changed-file evidence parsing and merged at `da3a4a5788e7019229d66247c360b258b1a5b1f7`.
- `#235` preferred the workflow token for same-repository post-approval merge/update and merged at `482b05c6c11d9da9895246406aca1c3bd8f6a691`.
- `#239` centralized the reasoning-effort guard and merged at `2aa1fa36255a558bafca05567125ef7e44571976` after current-head coverage, Strix, OpenCode, Noema, and scheduler evidence passed.
- `#242` added REST fallbacks for transient scheduler GraphQL reads and merged at `0d2c6d9e7ae1bad947e7ee3629e2a412ac2ce248`.
- `#244` added the central PR Review Autofix worker and merged at `4d2dd64028231b1154642bfe23b822fc3403e217`.
- `#246` hardened model-pool exhaustion handling and merged at `f5f00b782ae4f7806f0e3197bf9b49c9c5a2cb91`.
- Historical `#247` was not merged because it would have accepted previous-parent approval evidence after model exhaustion; its rejection is preserved as an explicit fail-closed precedent rather than a reusable approval path.
- `#249` constrained autofix dispatch to source-actionable current-head review findings and merged at `dbd33b3a0384de0129aa082a210383188d012415` after current-head evidence passed.
- `#255` removed the remaining deterministic low-risk approval fallback and merged at `e2beae72b87a8817cd57f9f51bab3947353baa61`; an initial review-publication rate limit was followed by a successful rerun and native auto-merge.
- `#283` refreshed reasoning-capable OpenCode configuration and merged at `ef9950e6b55bf943c0295e1df3e34c94210d21cc`.

## Preserved downstream incidents

- After `.github#255`, `ContextualWisdomLab/bandscope#493`, `#494`, `#495`, and `#500` were rechecked. Merge simulation found genuine conflicts, including `apps/desktop/src/App.tsx` and design-system documentation; those were conflict-repair findings, not update-branch candidates.
- `ContextualWisdomLab/aFIPC#78` eventually merged after current-head central `coverage-evidence`, `opencode-review`, `strix`, and `scan-pr-queue` passed on `b1ddafced86302f461e95259699f1efde5ec87c9` and OpenCode approved the same head.
- `ContextualWisdomLab/pg-erd-cloud#393` removed the repository-local autofix worker. Its first OpenCode run on `9d8eed5be47670b1b46f413295d9a6044d7327b2` exhausted the older pool; after `.github#246`, run `28485070313` approved the same head and the PR merged at `1e0d6a3dda5ea9afcd74dcd8380689672e1c8ef1`.
- A 2026-07-02 18:15 KST non-fork inventory found 17 public non-fork repositories, inherited ruleset `18156473` on `kaefa` and `waf-ids-ai-soc`, and no default-branch copies of the central OpenCode/Strix/scheduler workflows outside `.github`.
- `ContextualWisdomLab/waf-ids-ai-soc#6` merged at `e1c0a85fd4a8e6dd67039be43eb7f659fec22abd` after central required-workflow proof on head `43b62b5f347d1532c81b5ae38d8e41b4494fd486`; historical `#8@48d8b56a0f995829fc95de4fed129d1c33aaadff` was the next runtime-proof fixture.
- Historical `ContextualWisdomLab/kaefa#60@13c9089855fcdd34391173560ccf6935bac1eebe` exposed missing central-check materialization even though the repository inherited the ruleset; current PR state must always be re-read instead of inheriting that old status.

## Preservation invariant

The live ten-workflow contract supersedes the old seven-workflow operator state, but not the evidence explaining how it evolved. Future edits to the rollout summary may compact historical prose only when the semantic facts remain reconstructible from this record or another immutable evidence document. Current-head Checks, reviews, ruleset reads, and exact repository state always outrank this historical ledger for admission decisions.
