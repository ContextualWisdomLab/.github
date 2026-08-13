# Line-anchored OpenCode REQUEST_CHANGES findings

검토 기준일: **2026-08-13**

## Incident

OpenCode already posts GitHub pull-request reviews with a `comments: []` array so blockers can appear on the Files changed view. The control JSON required a positive `line`, but the trusted normalizer accepted any path string and any in-range integer. Two classes of output therefore survived the gate and then failed at the GitHub Reviews API:

1. A finding on a file that is not in the current-head changed-file list. GitHub's review-comment endpoints only accept a `path` that is part of the pull request diff; otherwise they return HTTP 422 (GitHub, n.d.-a, n.d.-b).
2. A finding whose `line` is past the current-head file length. That number cannot be a RIGHT-side blob line, so GitHub again rejects the inline comment. The workflow then has to explain the anchor failure instead of showing the blocker next to the code.

Unanchored blockers are also a weaker review artifact: modern code review is expected to name a concrete location the author can act on, not a file-level or repository-level remark (Bacchelli & Bird, 2013).

## Decision

`scripts/ci/opencode_review_normalize_output.py` now fail-closes each `REQUEST_CHANGES` finding through `finding_location_error()` before the review is published:

- `path` must be a non-empty string.
- When the trusted changed-file artifact is present, `path` must be an exact current-head changed file.
- The path/line pair must then pass the existing bounded source-tree probe (`adversarial_probe_location_error`): the file exists in `OPENCODE_SOURCE_WORKDIR`, is a regular file under the 2 MiB bound, and `line` is `<=` the current-head line count.

When the changed-file artifact is absent, membership cannot be proven; the source-tree existence and line-length checks still apply. Findings about files that *should* have been changed but were not belong in the review body, not in the inline `comments` array.

The reviewer prompt states the same contract: path is an exact current-head changed file; line is a positive integer that exists in that file; never line 0, an unchanged path, or a line past EOF.

This change does not alter APPROVE semantics, review-agent `edit: deny`, two-approval rules, or mention-dispatch.

## Verification contract

`tests/test_opencode_review_normalize_output.py` pins:

1. A finding on `scripts/ci/example.py:7` still validates.
2. A finding on `README.md` is rejected as not a current-head changed file.
3. A finding at line 999 is rejected as past EOF.
4. An empty path is rejected.
5. With the changed-file artifact removed, a missing path still fails because it does not exist in the trusted source tree.

`tests/test_opencode_agent_contract.py` pins the prompt phrases `exact current-head changed file` and `line past EOF`.

## Rollback

If a legitimate current-head blocker cannot be expressed as an exact changed-file path plus existing line, keep the finding in the review body and do not loosen the inline-comment gate. Do not accept `N/A`, line 0, or off-diff paths so that GitHub can attach a thread.

## References (APA 7th)

Bacchelli, A., & Bird, C. (2013). Expectations, outcomes, and challenges of modern code review. In *Proceedings of the 35th International Conference on Software Engineering* (pp. 712–721). IEEE. https://doi.org/10.1109/ICSE.2013.6606617

GitHub. (n.d.-a). *Create a review for a pull request*. GitHub Docs. Retrieved August 13, 2026, from https://docs.github.com/en/rest/pulls/reviews#create-a-review-for-a-pull-request

GitHub. (n.d.-b). *Create a review comment for a pull request*. GitHub Docs. Retrieved August 13, 2026, from https://docs.github.com/en/rest/pulls/comments#create-a-review-comment-for-a-pull-request
