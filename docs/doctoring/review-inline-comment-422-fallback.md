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
default 20), and retries each with the same write helper. A remapped
leftover that already has a multi-line GitHub suggestion range keeps
``start_line`` and ``start_side`` on those single-comment retries so
the replacement still applies as one range after the split (GitHub,
n.d.-b, n.d.-c). Comments past that cap are not posted as GitHub
suggestions: their ``path:start-end`` range and leftover LEFT origin
stay on the deferred overview list only, they are removed from the
applyable heading so the receipt does not claim GitHub can apply a
comment that was never sent, and they are recorded as not retried
instead of opening unbounded ``gh api`` writes. The first success uses `REQUEST_CHANGES` plus the review
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
n.d.-c). A LEFT-side leftover that still has an extractable replacement
is remapped onto a same-path current-head RIGHT hunk when one exists
(same line when that line is still commentable, otherwise the first
RIGHT line of the same ``@@`` hunk — not the first RIGHT line of the
whole path) so GitHub can apply it as a suggestion instead of a
manual edit (GitHub, n.d.-b, n.d.-c). The overview applyable receipt
then names both the RIGHT range GitHub will apply and the original
LEFT ``path:line`` (``from LEFT `path:line```) so the author can see
the finding moved. Local origin keys are stripped before the GitHub
POST. A LEFT line whose own hunk has no RIGHT side (a deletion hunk
inside a multi-hunk file) stays leftover. Only `+` lines become the
replacement; `n/a`, “cannot provide”, fence-breaking replacements, and
LEFT comments on paths with no RIGHT hunk (pure deletions) stay as the
original `` ```diff `` leftover. When the suggested_diff removes more
than one current-head line and every line from the finding through that
span sits on the same hunk, the comment also sets `start_line`, `line`,
and `start_side` so GitHub applies one multi-line suggestion range
(GitHub, n.d.-b). A range that would leave the hunk stays single-line.
The publisher then persists those applyable ranges as overview receipts
(``path:line`` or ``path:start-end``) so the author can see which hunks
shipped as one-click GitHub suggestions (GitHub, n.d.-c). Applyable vs
leftover uses a closed fence match, not a bare `` ```suggestion ``
substring (CWE-1288; MITRE, n.d.). A leftover mention of the token, and
every LEFT suggestion, stay leftover. Comments that
kept only a `` ```diff `` fence are listed separately with the reason
``cannot-provide`` (``n/a``, “cannot provide”, fence-breaking
replacement, or no ``+`` lines) or ``LEFT`` (GitHub cannot apply a
suggestion on the deleted side; GitHub, n.d.-b, n.d.-c). Each leftover
row also keeps a bounded excerpt of that fence as a distinct
“Manual edit (not a GitHub suggestion):” `` ```diff `` block so the
author can copy the replacement by hand. Excerpts drop ``<!--``, ``-->``,
and HTML metacharacters so leftover text cannot close
``<!-- opencode-review-overview -->`` (CWE-116; MITRE, 2026). That block
is never a GitHub
`` ```suggestion `` fence and is never listed under the applyable
``path:line`` / ``path:start-end`` heading (GitHub, n.d.-c). A comment
that already has `` ```suggestion `` is applyable, not leftover.
Suggested diffs still stay out of the PR-level body.

The publisher calls this helper from `build_inline_comment_failure_body`
with the same control object used to build the inline `comments` array.

## Verification contract

- `tests/test_opencode_inline_comment_fallback.py` pins safe-pair extraction,
  the exact location list, GitHub JSON `errors[].message` phrases, HTTP 422
  line fallback, empty-set sentence, CLI success with `--error-file`,
  fail-closed unreadable control or error input, batch-to-single comment
  splitting, `--is-unprocessable` classification, mixed-success
  receipts that list attached path:line beside refused path:line,
  per-comment 422 phrases, the 20-comment one-at-a-time retry cap,
  preservation of ``start_line``/``start_side`` on remapped multi-line
  suggestion retries, deferred leftovers past the retry cap that keep
  range and LEFT origin as non-applyable overview context, and
  leftover path:line rows that were not retried, unified-diff hunk
  parsing, the pre-POST filter that drops off-hunk comments, and
  conversion of surviving suggested diffs into GitHub suggestion blocks,
  `start_line`/`line` ranges when a multi-line replacement sits on one
  current-head hunk, overview receipts that list applyable
  ``path:start-end`` suggestion ranges, and a separate leftover-diff
  receipt list that labels remaining `` ```diff `` fences as
  ``cannot-provide`` or ``LEFT`` and renders their replacement text as
  a non-applyable manual-edit `` ```diff `` block, and remapping of
  applyable LEFT leftovers onto a same-path RIGHT hunk so they become
  GitHub suggestion ranges, using the same ``@@`` hunk rather than the
  first RIGHT line of the whole path, and overview labels that name
  the original LEFT ``path:line`` beside the applyable RIGHT range.
- `tests/test_opencode_agent_contract.py` and
  `scripts/ci/test_strix_quick_gate.sh` pin the workflow call with
  `$control_json`.

## Rollback

If GitHub later accepts off-diff comments, keep citing the attempted
`path:line` in the fallback. Do not restore a location-free sentence.

## References (APA 7th)

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

MITRE. (n.d.). *CWE-1288: Improper validation of unsafe equivalence in input*.
Retrieved August 13, 2026, from https://cwe.mitre.org/data/definitions/1288.html

Sadowski, C., Söderberg, E., Church, L., Sipko, M., & Bacchelli, A. (2018).
Modern code review: A case study at Google. In *Proceedings of the 40th
International Conference on Software Engineering: Software Engineering in
Practice* (pp. 181–190). ACM. https://doi.org/10.1145/3183519.3183525
