# Dashboard: `pull_request_target` evaluate → enforce (2026-11-02)

**Status:** tracked · audit complete · policy draft ready (lead apply) · **Not** current QUEUED root cause  
**Sources:** [changelog 2026-09-17](https://github.blog/changelog/2026-09-17-workflow-execution-protections-in-github-actions-generally-available/), [Actions policies REST](https://docs.github.com/en/rest/actions/policies), live org/repo API 2026-09-20T10:25Z (reconfirmed worker 2026-09-20T10:35Z)  
**Issue:** [ContextualWisdomLab/.github#2293](https://github.com/ContextualWisdomLab/.github/issues/2293)  
**Doctoring:** [`docs/doctoring/prt-evaluate-trust-path-audit-20260920.md`](../doctoring/prt-evaluate-trust-path-audit-20260920.md)  
**Policy draft (do not POST):** [`infra/actions/policies/org-prt-central-allowlist-evaluate.json`](../../infra/actions/policies/org-prt-central-allowlist-evaluate.json)

## Current policy (live)

| Layer | Observation |
| --- | --- |
| Org `GET /orgs/ContextualWisdomLab/actions/policies?has_parents=true` | `total_count=0`, `policies=[]` — **no** custom Actions event/actor policy |
| Repo samples (`.github`, bandscope, disksage, naruon, noema, appguardrail) | each `total_count=0` |
| Classic Actions permissions | org `enabled_repositories=all`, `allowed_actions=all`; `.github` same |
| Default GitHub rule (public, no applicable event policy) | **evaluate** now (runs continue; Insights would-list blocks); **enforce 2026-11-02** blocks `pull_request_target` unless an explicit policy allows it |
| Private / internal | default rule **does not apply** (org has **73** public, **10** private) |
| Insights REST | no `…/insights` under policies on this token (UI Insights still authoritative for would-block runs) |

**Implication:** all **73 public** repos currently sit on GitHub’s default evaluate policy for `pull_request_target`. That is distinct from runner admission / QUEUED capacity.

## Central inventory (ContextualWisdomLab/.github)

Only four workflow files declare `on.pull_request_target` in the central repo (verified 2026-09-20):

| Workflow | Trigger | Secrets / token on PRT path | Untrusted PR head | Cache / artifact | PRT decision |
| --- | --- | --- | --- | --- | --- |
| `opencode-review.yml` | `pull_request_target` (+ types incl. closed/draft) | Admission/cleanup tokens; comment: no PR checkout / no secret bind on this entry | Metadata + dispatch only; fork PRs rejected | no | **Keep** |
| `opencode-review-dispatch.yml` | `repository_dispatch` only | Privileged review path | Exact-head materialization under trusted controls | yes | N/A (already safe event) |
| `noema-review.yml` | `pull_request_target` + `repository_dispatch` | `NOEMA_*`, provider keys, publication token (post trusted tarball + live-head gate) | Same-repo head required; stale heads retired | upload-artifact (failure evidence) | **Keep** |
| `strix.yml` | `push` + `pull_request_target` + dispatch + schedule | Approve/merge tokens, LLM keys (post sidecar) | **Base** checkout; PR scope copied with execute bits stripped (`__PR_SCOPE__`) | cache + artifact | **Keep** |
| `pr-review-merge-scheduler.yml` | `push` + `pull_request_target` + `pull_request_review` + `workflow_call` + schedule + dispatch | `PR_REVIEW_MERGE_TOKEN` / app token | Head metadata only (no code exec from head) | no | **Keep** (conversion deferred — see below) |
| `opencode-review-coalesce-tick.yml` | `schedule` | yes | none | — | N/A |

Ruleset `18156473` (`CWL Central required workflows`) injects central workflows into target repos on `~DEFAULT_BRANCH`, excluding `.github`, `noema`, `IRT-bibliography-set`. Those three still run local/classic copies of the same workflow files from `.github`.

**Hard bans for remediation:** no unconditional org-wide allow of all events; no `allow-unsafe-pr-checkout`; no removal of security gates / required checks.

## Trust-path audit (2026-09-20 worker)

Full prose: [`docs/doctoring/prt-evaluate-trust-path-audit-20260920.md`](../doctoring/prt-evaluate-trust-path-audit-20260920.md).

| Check | OpenCode | Noema | Strix | Merge scheduler |
| --- | --- | --- | --- | --- |
| Secrets stay base-context / post-trust gate | ✓ (no secrets on PRT entry) | ✓ | ✓ (LLM after sidecar) | ✓ (mutation token scoped) |
| No PR-head install/build/exec on PRT path | ✓ | ✓ (API + tarball) | ✓ (`__PR_SCOPE__`) | ✓ (metadata scheduler) |
| Live exact-head revalidation | ✓ | ✓ | ✓ | ✓ |
| Cancel only superseded/inactive via `(repo,pr,head)` composite | ✓ | ✓ | ✓ | ✓ (coalescer) |
| Fork / cross-repo head blocked or materialized safely | ✓ reject fork | ✓ same-repo only | ✓ tuple gate | ✓ allowlist dispatch |

### Conversion outcome

- **No workflow trigger conversion merged in this pass.** Every surviving file still requires `pull_request_target` for ruleset `18156473` fan-out and/or primary PR-event wake (`opened`, `synchronize`, `ready_for_review`, …).
- **`pr-review-merge-scheduler.yml`** remains the best *future* candidate: `pull_request_review`, `repository_dispatch`, and `schedule` already exist, but they do not cover the ruleset-injected PR sync wake that drives queue scan + review dispatch on 73 public siblings. Removing PRT without a replacement wake contract would stall merge automation.

## Minimal org policy draft (lead apply)

File: [`infra/actions/policies/org-prt-central-allowlist-evaluate.json`](../../infra/actions/policies/org-prt-central-allowlist-evaluate.json)

| Field | Value |
| --- | --- |
| `enforcement` | `evaluate` first (lead may promote to `active` after Insights) |
| `conditions.workflow_path.include` | four central paths only (not `~ALL`) |
| `rules[0].type` | `restrict_action_events` |
| `allowed_events` | union of legitimate triggers those files already use: `pull_request_target`, `pull_request_review`, `repository_dispatch`, `push`, `schedule`, `workflow_call` |

Apply command (lead only, after review):

```bash
gh api -X POST orgs/ContextualWisdomLab/actions/policies \
  --input infra/actions/policies/org-prt-central-allowlist-evaluate.json
```

Record returned `id` here after apply: `_pending_`

## Affected repos (enforce class)

- **In scope for 11/2 default enforce:** 73 public repositories with empty Actions policies (org-wide).
- **Out of scope for default rule:** 10 private repositories.
- **Operational blast radius:** every public default-branch PR that relies on required OpenCode / Noema / Strix / Merge Scheduler contexts via `pull_request_target` (ruleset fan-out + `.github` classic BP).

## Completion criteria before 2026-11-02

1. **Inventory closed:** every central (and drift-copy) workflow with `on.pull_request_target` classified keep / convert / allowlist-with-path. **Done (2026-09-20):** all four central files → **keep**; dispatch-only paths N/A.
2. **Conversions merged:** any PRT trigger that is not required for base-context or secrets is moved to `pull_request`, `pull_request_review`, `repository_dispatch`, or `schedule` without losing exact-head evidence contracts. **Deferred:** no safe conversion identified; documented in doctoring record.
3. **Minimal event policy (only if still needed):** org Actions policy with `restrict_action_events` allowing `pull_request_target` **only** for named `workflow_path.include` of surviving central files (file targeting), `enforcement=active` (or `evaluate` first on Enterprise if available), never `~ALL` workflows. **Draft ready; lead POST pending.**
4. **Trust re-verify:** secrets stay base-context; no PR-head install/build/exec; caches/artifacts not writable from untrusted head; contract tests still pin the trust boundary. **Done (audit); CI unchanged.**
5. **Proof:** after policy/workflow change, a public-repo PR still posts Required OpenCode / Noema / Strix / Merge Scheduler on the live head; Insights show no unexpected would-block for those paths; dashboard updated with policy id(s). **Open.**
6. **Non-goals:** do not attribute current hosted QUEUED starvation to evaluate mode; do not weaken Scorecard/Semgrep/CodeQL/Strix gates. **Honored.**

## Worker assignment

MBA-placed worker owns trust-path deep audit + scoped conversion PR + draft minimal policy JSON (no apply until lead review). Lead keeps merge-prep / cancel pause / QUEUED capacity track separate.

**Worker `task_feb9d18ebe93` (2026-09-20):** audit + dashboard + policy draft + doctoring complete; no workflow YAML edits (no safe conversion); policy apply left to lead.
