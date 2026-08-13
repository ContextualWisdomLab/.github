# GitHub 422 inline-comment fallback cites trusted path:line

검토 기준일: **2026-08-13**

## Incident

When GitHub rejects an OpenCode `REQUEST_CHANGES` review because one or more
inline comments cannot attach, the publisher already falls back to a PR-level
body and does not copy suggested diffs into that body. The fallback sentence
said only “the cited finding lines.” Authors then had to open the workflow log
or control JSON to learn *which* `path:line` GitHub refused (GitHub, n.d.-a,
n.d.-b). That is weaker than the line-anchored review artifact modern code
review expects (Bacchelli & Bird, 2013).

## Decision

`scripts/ci/opencode_inline_comment_fallback.py` reads the trusted control
JSON, keeps first-seen safe relative `path` plus positive integer `line`
pairs, and appends them to the fallback body as `` `path:line` `` list
items. Unsafe paths (`..`, absolute, drive, backslash) and non-positive
lines are omitted. An empty location set is stated explicitly.

After a refused attach, the publisher first checks that the failure is
HTTP 422, splits the batch `comments` array into at most 20
single-comment review payloads (`OPENCODE_INLINE_COMMENT_RETRY_LIMIT`,
default 20), and retries each with the same write helper. Comments past
that cap are recorded as not retried instead of opening unbounded `gh
api` writes. The first success uses `REQUEST_CHANGES` plus the review
body; later successes use `COMMENT`. Survivors therefore still appear on
Files changed. Remaining failures still rebuild the fallback from the
`gh api` error file and write durable receipts into the OpenCode
overview comment (`<!-- opencode-review-overview -->`). On mixed success
the overview lists attached `path:line` rows beside refused `path:line`
rows (each refused row keeps that comment's own 422 phrase) and any
locations left untried by the retry cap. JSON `errors[].message` such as
`pull_request_review_thread.path is invalid`, or the first `HTTP 422`
line, is the phrase source. A later comment's different GitHub error
does not overwrite an earlier one. URLs are stripped and each phrase is
bounded to 240 characters.

Before the first GitHub POST, the publisher runs
`git diff --unified=3` from the merge base to the current head and keeps
only comments whose `path:line` sits inside a parsed hunk range, including
hunk context lines. GitHub accepts review comments only on those diff
hunks (GitHub, n.d.-b); off-hunk comments are recorded as skipped
`path:line` receipts instead of being sent. An empty hunk map leaves the
payload unchanged so a failed diff collection cannot drop every comment.
This matches the modern-review expectation that discussion belongs on the
changed hunk rather than elsewhere in the file (Bacchelli & Bird, 2013;
Sadowski et al., 2018).

After that filter, surviving RIGHT-side comments convert their
`` ```diff `` suggested-diff fence into a GitHub `` ```suggestion ``
block so the author can apply the replacement in one click (GitHub,
n.d.-c). Only `+` lines become the replacement; `n/a`, “cannot provide”,
LEFT-side comments, and replacements that would break the fence stay as
the original `` ```diff `` context. Suggested diffs still stay out of the
PR-level body.

The publisher calls this helper from `build_inline_comment_failure_body`
with the same control object used to build the inline `comments` array.

## Verification contract

- `tests/test_opencode_inline_comment_fallback.py` pins safe-pair extraction,
  the exact location list, GitHub JSON `errors[].message` phrases, HTTP 422
  line fallback, empty-set sentence, CLI success with `--error-file`,
  fail-closed unreadable control or error input, batch-to-single comment
  splitting, `--is-unprocessable` classification, mixed-success
  receipts that list attached path:line beside refused path:line,
  per-comment 422 phrases, the 20-comment one-at-a-time retry cap, and
  leftover path:line rows that were not retried, unified-diff hunk
  parsing, the pre-POST filter that drops off-hunk comments, and
  conversion of surviving suggested diffs into GitHub suggestion blocks.
- `tests/test_opencode_agent_contract.py` and
  `scripts/ci/test_strix_quick_gate.sh` pin the workflow call with
  `$control_json`.

## Rollback

If GitHub later accepts off-diff comments, keep citing the attempted
`path:line` in the fallback. Do not restore a location-free sentence.

## References (APA 7th)

MITRE. (2026). *CWE-1288: Improper validation of syntactic correctness of
input*. https://cwe.mitre.org/data/definitions/1288.html

Bacchelli, A., & Bird, C. (2013). Expectations, outcomes, and challenges of
modern code review. In *Proceedings of the 35th International Conference on
Software Engineering* (pp. 712–721). IEEE.
https://doi.org/10.1109/ICSE.2013.6606617

GitHub. (n.d.-a). *Create a review for a pull request*. GitHub Docs. Retrieved
August 13, 2026, from
https://docs.github.com/en/rest/pulls/reviews#create-a-review-for-a-pull-request

GitHub. (n.d.-b). *Create a review comment for a pull request*. GitHub Docs.
Retrieved August 13, 2026, from
https://docs.github.com/en/rest/pulls/comments#create-a-review-comment-for-a-pull-request

GitHub. (n.d.-c). *Commenting on a pull request*. GitHub Docs. Retrieved
August 13, 2026, from
https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/commenting-on-a-pull-request#suggesting-changes-to-a-file

Sadowski, C., Söderberg, E., Church, L., Sipko, M., & Bacchelli, A. (2018).
Modern code review: A case study at Google. In *Proceedings of the 40th
International Conference on Software Engineering: Software Engineering in
Practice* (pp. 181–190). ACM. https://doi.org/10.1145/3183519.3183525
