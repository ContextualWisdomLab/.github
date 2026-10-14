# Trust-path audit: central `pull_request_target` workflows (2026-09-20)

**Issue:** ContextualWisdomLab/.github#2293  
**Dashboard:** [`docs/triage/prt-evaluate-policy-20260920.md`](../triage/prt-evaluate-policy-20260920.md)  
**Policy draft (not applied):** [`infra/actions/policies/org-prt-central-allowlist-evaluate.json`](../../infra/actions/policies/org-prt-central-allowlist-evaluate.json)

## Scope

Deep audit of the four central workflows that still declare `on.pull_request_target` in
`ContextualWisdomLab/.github`, plus ruleset `18156473` fan-out behavior. Non-goals: attributing
hosted QUEUED admission to GitHub evaluate mode; unconditional org-wide PRT allow; `allow-unsafe-pr-checkout`;
removing security gates.

## Summary verdict

| Workflow | PRT decision | Rationale |
| --- | --- | --- |
| `opencode-review.yml` | **Keep** | Required-check entry; metadata-only on PRT path; privileged work isolated in `opencode-review-dispatch.yml` (`repository_dispatch`). |
| `noema-review.yml` | **Keep** | Same-repo head gate; trusted tarball materialization; publication requires scoped reviewer token on exact live head. |
| `strix.yml` | **Keep** | Base checkout + `__PR_SCOPE__` execute-bit strip; LLM keys only after trusted gate; required PR evidence via ruleset. |
| `pr-review-merge-scheduler.yml` | **Keep (conversion deferred)** | Ruleset-injected wake on `opened`/`synchronize`/… still requires PRT; `pull_request_review` + `schedule` + `repository_dispatch` do not replace that primary queue scan path. |

No safe PRT→`pull_request` conversion landed in this pass without breaking ruleset `18156473` required-check contracts or fork/base-context trust boundaries.

## Per-workflow trust path

### `opencode-review.yml`

- **Trigger:** `pull_request_target` only (plus job-level gates for closed/draft).
- **Secrets / token:** Default `github.token` on the PRT path; OIDC + OpenCode app token only inside the dispatch step to POST `repository_dispatch` on `.github`. No repository secrets bound on the PRT entry jobs.
- **Checkout / exec:** Explicitly no PR checkout or PR-content execution on the required-check jobs; trusted policy tarball fetched from immutable `workflow_sha` via GitHub API.
- **Untrusted head:** Fork PRs rejected before admission (`head.repo != base.repo`). Live-head revalidation on every dispatch/verdict step.
- **Cache / artifact:** None on the PRT path.
- **Cancellation:** Superseded-head cleanup matches composite `(repo, pr, head)` via `display_title` and/or `pull_requests[]` — never bare `head_sha` alone.

### `noema-review.yml`

- **Trigger:** `pull_request_target` + `repository_dispatch` retry path.
- **Secrets / token:** `NOEMA_*`, provider LLM keys, publication token — all after trusted tarball materialization and live-head validation. Same-repo head required on PRT (`head.repo.full_name == github.repository`).
- **Checkout / exec:** Trusted `.github` tarball at immutable `workflow_sha`; `two_phase.py` reads PR via API, not PR-head checkout.
- **Untrusted head:** Fork and stale heads rejected at admission; superseded-run cancellation re-verifies live head before each cancel.
- **Cache / artifact:** Sidecar failure uploads read-only evidence artifacts; no PR-writable cache keys observed.

### `strix.yml`

- **Trigger:** `push`, `pull_request_target`, `schedule`, `repository_dispatch`.
- **Secrets / token:** LLM provider keys post sidecar; optional `PR_REVIEW_MERGE_TOKEN` / `OPENCODE_APPROVE_TOKEN` on cleanup/admission only.
- **Checkout / exec:** Trusted Strix source from central ref; target workspace materialized at **base** SHA; PR head fetched as data into isolated scope. Scan executes with `STRIX_TARGET_PATH=__PR_SCOPE__` and execute bits stripped on copied blobs.
- **Untrusted head:** Live PR tuple validated before scan; same-repo dispatch metadata enforced.
- **Cache / artifact:** `strix-reports` artifact upload from trusted workspace paths; pip `--no-cache-dir` on install.

### `pr-review-merge-scheduler.yml`

- **Trigger:** `push`, `pull_request_target`, `pull_request_review`, `workflow_call`, `schedule`, `repository_dispatch`.
- **Secrets / token:** `PR_REVIEW_MERGE_TOKEN` / OpenCode app token for cross-repo mutations; default token for same-repo coalesce job.
- **Checkout / exec:** Trusted scheduler tarball at `workflow_sha`; Python scheduler uses GraphQL/REST metadata only — no PR-head install/build/exec.
- **Untrusted head:** Targeted `repository_dispatch` allowlisted via `OPENCODE_REPOSITORY_DISPATCH_TARGETS`; live PR tuple validated.
- **Cache / artifact:** None.
- **Conversion note:** Removing PRT would drop ruleset-driven wakes on PR open/sync/ready for 70+ public siblings; daily `schedule` and review events alone are insufficient for current-head merge automation latency.

## Policy draft

Minimal org allowlist: [`infra/actions/policies/org-prt-central-allowlist-evaluate.json`](../../infra/actions/policies/org-prt-central-allowlist-evaluate.json)

- `workflow_path.include` lists only the four surviving central files (never `~ALL`).
- `restrict_action_events.allowed_events` is the union of legitimate triggers those files use (PRT plus non-PRT triggers they already declare).
- `enforcement: evaluate` first; flip to `active` after Insights shows no unexpected would-blocks for required contexts.
- **Lead apply only** — worker did not POST.

## Proof still owed before 2026-11-02 enforce

1. Lead POSTs policy (evaluate → active after review).
2. Public-repo PR demonstrates Required OpenCode / Noema / Strix / Merge Scheduler contexts on live head.
3. Dashboard updated with policy id(s) and Insights screenshot or API evidence.
