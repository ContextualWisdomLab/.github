# Reusable scheduler control runner

## Cause and assignment

On 2026-09-27, fast-mlsirm#2199 still had 21 queued checks despite five online self-hosted runners. Four runners were busy; cwlab-s1-05 was idle. The central control group admitted only the .github repository, while the reusable scheduler explicitly sent consumer repositories to hosted Ubuntu. Adding runners alone did not remove either access/routing constraint.

The assignment minimizes hosted admission for trusted scheduler work subject to one dedicated control runner and separation from long model, scanner, and PR build execution. With one eligible control pool, the assignment is direct; no optimizer dependency or speculative duration weights are needed. Existing CodeQL/OpenCode pools and live inference are preserved.

## Change and trust boundary

The reusable scheduler uses group `CWL central control` and labels `[self-hosted, linux, x64]` for every caller. Runner group `CWL central control` must grant organization repository access while retaining `restricted_to_workflows=true` and exactly the three existing central `@refs/heads/main` workflow paths: agent-mention-router, hourly-review-repair, and pr-review-merge-scheduler. This permits only jobs directly defined in trusted central workflows, not arbitrary caller jobs. The scheduler materializes only the immutable central workflow source; PR source execution is unchanged. Security gates, review verdicts, provider policy, and model duration remain unchanged.

## Verification

Run the scheduler runner-image contract, required-workflow queue contracts, and actionlint. After integration, inspect the actual runner name of a targeted dry-run dispatch; config acceptance is not execution proof. No skipped/queued checks are represented as successful tests. User explicitly authorized bypass merge for blocked CI on this task.

## References

GitHub. (n.d.). *Managing access to self-hosted runners using groups*. https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/manage-access

GitHub. (n.d.). *Reusing workflow configurations*. https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations
