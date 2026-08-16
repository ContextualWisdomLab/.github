# Hunk-anchored OpenCode REQUEST_CHANGES findings

검토 기준일: **2026-08-17**

## Incident

GitHub's pull-request review-comment API accepts a `path` plus a RIGHT-side
`line` only when that line sits in the pull-request diff (GitHub, n.d.-a,
n.d.-b). Commenting on an unchanged line of a changed file, or on a line
outside every `@@` hunk, returns HTTP 422. The trusted approve gate already
rejected those findings (`changed_new_lines` in
`opencode_review_approve_gate.sh`), but the Python normalizer published them
first. Reviewers then saw a review body without the inline thread that
CodeRabbit-style blockers require (Bacchelli & Bird, 2013).

Rewriting `.github/workflows/opencode-review-dispatch.yml` to carry a new
sealed artifact is not available: that workflow is a hashed blob
(`83f6830d5c21a324b4dbcd4e5c21a07968994b81`) and rewriting it breaks the
review-agent key contract.

## Decision

`opencode_adversarial_receipts.py` lists every RIGHT-side hunk line from
`git diff --unified=0` and prints `OPENCODE_CHANGED_HUNK_LINE` tokens into the
already-sealed evidence file. Paths that contain backticks, HTML
metacharacters, `-->`, `<!--`, a suggestion fence, spaces, or `=` are omitted
so a leftover cannot close the overview HTML comment or split a token
(CWE-116). `finding_hunk_location_error()` fail-closes a `REQUEST_CHANGES`
finding when that sealed evidence (or an optional dedicated hunk-lines
artifact) is present and the cited line is not in the hunk set. A leftover
`start_line` that sits off-hunk also fails closed even when `line` is
attachable, because GitHub 422s the multi-line leftover range. A sealed empty
manifest (`OPENCODE_CHANGED_HUNK_LINE none`) is present evidence, so every
cited line is rejected instead of being confused with a missing artifact. When
neither the dedicated artifact nor the evidence tokens are present, the check
is a no-op so local unit tests that do not simulate the workflow stay valid.

The hashed review-dispatch workflow is unchanged. The approve-gate hunk check
remains the second line of defense. Reviewers stay `edit: deny`.

## Verification contract

- `tests/test_opencode_review_normalize_output.py` rejects line 8 and accepts
  line 7 when the trusted hunk artifact lists `scripts/ci/example.py:7`, and
  rejects every line when that sealed artifact lists no RIGHT-side hunk rows.
- The same module reads `OPENCODE_CHANGED_HUNK_LINE` tokens from sealed
  evidence when the dedicated artifact env is absent, matching production CI
  that keeps `opencode-review-dispatch.yml` at blob `83f6830d`.
- `tests/test_opencode_adversarial_receipts.py` proves the manifest lists every
  hunk line, not only first/last span endpoints.
- `tests/test_opencode_agent_contract.py` pins the prompt phrases
  `current-head changed hunk` and `outside the focused diff hunks`.

## Rollback

If a legitimate blocker cannot be expressed as a current-head hunk line, keep
it in the review body. Do not loosen the inline-comment gate to accept
off-diff lines. Do not rewrite the hashed dispatch workflow to carry the
check.

## References (APA 7th)

Bacchelli, A., & Bird, C. (2013). Expectations, outcomes, and challenges of
modern code review. In *Proceedings of the 35th International Conference on
Software Engineering* (pp. 712–721). IEEE.
https://doi.org/10.1109/ICSE.2013.6606617

GitHub. (n.d.-a). *Create a review for a pull request*. GitHub Docs. Retrieved
August 17, 2026, from
https://docs.github.com/en/rest/pulls/reviews#create-a-review-for-a-pull-request

GitHub. (n.d.-b). *Create a review comment for a pull request*. GitHub Docs.
Retrieved August 17, 2026, from
https://docs.github.com/en/rest/pulls/comments#create-a-review-comment-for-a-pull-request

MITRE. (n.d.). *CWE-116: Improper encoding or escaping of output*. CWE.
Retrieved August 17, 2026, from https://cwe.mitre.org/data/definitions/116.html
