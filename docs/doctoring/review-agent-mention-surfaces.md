# Review-agent mention surfaces and review compute allocation

검토 기준일: **2026-08-13**

## Incident

Trusted maintainers invoked `@cwl-noema-review` and `@opencode-agent` from
pull-request line comments and submitted review bodies. Those GitHub events
(`pull_request_review_comment`, `pull_request_review`) do not include an
`issue.pull_request` marker. The mention parser treated the absence of that
marker as “not a pull request” and returned no request. The five-minute
organization sweep listed only `issues/{n}/comments`, so it could not recover
the missed invocation. The local workflow job also required a case-sensitive
`contains(..., '@cwl-noema-review')` match on the conversation-comment body.

That miss left open pull requests without a second independent review. The
organization requires two approvals, and the only human collaborator is usually
the author, so a silent mention path is a merge deadlock rather than a
convenience gap.

## Decision

Accept three mention surfaces that share the same trust checks
(`OWNER` / `MEMBER` / `COLLABORATOR`, non-bot, exact handle, open PR, live
head SHA):

1. Issue comments on a pull request (`issue.pull_request` present).
2. Pull-request review comments (no `issue`; bind `pull_request.number`).
3. Submitted review bodies (no `issue`; skip pending and dismissed
   reviews and reviews older than the sweep lookback).

The workflow hydrates `PR_NUMBER` from `github.event.issue.number ||
github.event.pull_request.number`. Body-handle filtering stays in the
case-insensitive Python parser. Issue-comment eye reactions stay on the
issue-comment reaction endpoint and are non-fatal: live run
`31670687388` queued `@cwl-noema-review` on
ContextualWisdomLab/.github#954 and then failed the job with
`403 Resource not accessible by integration` on the reaction POST, so no
receipt was posted. Review-comment and review identifiers are not
issue-comment IDs, so those surfaces acknowledge only with the existing
receipt issue comment. The local job uses `pull-requests: write` so
conversation receipts on pull requests can be created, and
`reactions: write` so the optional eyes reaction is an allowed GitHub
App write. Live `route-local-agent-mention` run `31686563920` still
failed on `main` after dispatch because the default-branch job token
lacked `reactions` and POST `/issues/comments/{id}/reactions` returned
`403 Resource not accessible by integration`.

CWE-755 forbids treating an exceptional secondary condition as a primary
failure (MITRE, 2026). A 403 on the optional eyes reaction is therefore a
warning, not a missed dispatch.

Review thoroughness is tightened in the existing prompts rather than by adding
a second reviewer product. Every current-head changed file must be named in
the review summary. Compact four-step `ci-review` enumerates files and
obvious blockers; the twelve-step fallback decomposes remaining files and
ablates hypotheses against current-head evidence. Speed is not a success
metric. Review agents remain `edit: deny`. The LLM key remains
`NVIDIA_NIM_API_KEY`.

## Verification contract

`tests/test_agent_mention_router.py` and `tests/test_agent_mention_sweep.py`
drive `parse_event` and `build_requests_for_pull_request` with GitHub-shaped
review-comment and submitted-review payloads, including mixed-case handles.
`tests/test_agent_mention_workflow_contract.py` pins the new workflow triggers
and the absence of the case-sensitive body `contains` filter.
`tests/test_opencode_agent_contract.py` pins the per-file walk and
Fugu / Conductor / TRINITY allocation strings. Permanent quality remains
100% statement/branch coverage and 100% public docstrings on `scripts/ci`.

## Rollback

Revert the parser, sweep, workflow trigger/`if`/hydrate, prompt, and contract
test changes together. Do not restore the `issue.pull_request`-only gate or the
case-sensitive workflow body filter without a replacement that still accepts
review comments and mixed-case handles.

## References (APA 7th)

MITRE. (2026). *CWE-755: Improper handling of exceptional conditions*.
https://cwe.mitre.org/data/definitions/755.html

GitHub. (n.d.). *Events that trigger workflows*. GitHub Docs. Retrieved
August 13, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

GitHub. (n.d.). *REST API endpoints for pull request review comments*. GitHub
Docs. Retrieved August 13, 2026, from
https://docs.github.com/en/rest/pulls/comments

GitHub. (n.d.). *REST API endpoints for pull request reviews*. GitHub Docs.
Retrieved August 13, 2026, from
https://docs.github.com/en/rest/pulls/reviews

Lu, C., Holt, S., Fanconi, C., Chan, A. J., Lange, R. T., Foerster, M.,
Tegmark, M., & Lange, R. (2025). *The AI scientist-v2: Workshop-level automated
scientific discovery via agentic tree search* (arXiv:2504.08066). arXiv.
https://doi.org/10.48550/arXiv.2504.08066

Sakana AI. (2025). *Conductor: Orchestrating heterogeneous language-model
compute* (arXiv:2512.04695). arXiv. https://arxiv.org/abs/2512.04695

Sakana AI. (2025). *TRINITY: Role-separated multi-agent critique*
(arXiv:2512.04388). arXiv. https://arxiv.org/abs/2512.04388

Sakana AI. (2026). *Fugu: Inference-level ablation for test-time compute*
(arXiv:2606.21228). arXiv. https://arxiv.org/abs/2606.21228
