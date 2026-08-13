# OpenCode approval must name every current-head changed file

검토 기준일: **2026-08-13**

## Incident

The OpenCode normalizer accepted an APPROVE when the reason/summary named
*one* current-head path. CodeRabbit-style reviews walk every changed file.
Buyers comparing the two saw OpenCode approve after a single path citation
while leaving the rest of the diff unnamed. That is the “less detailed than
CodeRabbit” gap.

## Decision

`unnamed_changed_files(reason, summary, findings=None)` returns every path
from `current_changed_files()` that is not named as a whole path token,
is not a REQUEST_CHANGES finding path, and is not cited by an identical
``diff --git a/X b/X`` header in that finding's suggested diff. A
mismatched ``a/`` and ``b/`` pair names neither path. A longer sibling
such as ``example.py.bak`` contains ``example.py`` as a prefix substring;
that is not a disposition of the shorter file (CWE-1288; MITRE, 2026).
``path:line`` still counts. `valid_control` rejects APPROVE and
REQUEST_CHANGES when that tuple is non-empty. A REQUEST_CHANGES finding
on one file plus a named no-blocker disposition of the rest is enough;
a blocker-only review that never mentions the other files is not.

An empty changed-file set remains a no-op (`()`), so identity-only PRs are
unchanged.

IEEE 1028 requires every software product in the review package to
receive a recorded disposition (IEEE, 2008). Naming one path therefore
cannot authorize APPROVE when the trusted artifact lists more files.

## Trust boundary

Changed-file identity still comes from the trusted workflow artifact, not
from model prose. The model cannot invent a smaller file set to pass the
walk.

## Verification contract

`test_approval_must_name_every_current_head_changed_file` uses a two-file
current-head list (`scripts/ci/example.py` and `.github/workflows/strix.yml`).
Naming only the first file is rejected. Naming both is accepted. A post-repair
reason that drops the second path is still rejected. Naming only
``scripts/ci/example.py.bak`` still leaves ``scripts/ci/example.py`` unnamed.
`test_request_changes_must_name_every_current_head_changed_file` rejects a
REQUEST_CHANGES finding on only the first file, accepts a finding plus a
named no-blocker on the second, and accepts findings that cover both paths.

## Rollback

Remove the `unnamed_changed_files` checks from the two APPROVE blocks,
the REQUEST_CHANGES block, and the helper. Existing “at least one file”
detection remains.

## References (APA 7th)

MITRE. (2026). *CWE-1288: Improper validation of consistency within input*.
https://cwe.mitre.org/data/definitions/1288.html

IEEE. (2008). *IEEE standard for software reviews and audits* (IEEE Std
1028-2008). https://doi.org/10.1109/IEEESTD.2008.4601584

Bacchelli, A., & Bird, C. (2013). Expectations, outcomes, and challenges of
modern code review. In *Proceedings of the 35th International Conference on
Software Engineering* (pp. 712–721). IEEE.
https://doi.org/10.1109/ICSE.2013.6606617

GitHub. (n.d.). *About pull request reviews*. GitHub Docs. Retrieved
August 13, 2026, from
https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/about-pull-request-reviews
