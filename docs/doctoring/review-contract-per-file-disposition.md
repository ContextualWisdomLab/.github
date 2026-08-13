# OpenCode approval must name every current-head changed file

검토 기준일: **2026-08-13**

## Incident

The OpenCode normalizer accepted an APPROVE when the reason/summary named
*one* current-head path. CodeRabbit-style reviews walk every changed file.
Buyers comparing the two saw OpenCode approve after a single path citation
while leaving the rest of the diff unnamed. That is the “less detailed than
CodeRabbit” gap.

## Decision

`unnamed_changed_files(reason, summary)` returns every path from
`current_changed_files()` that is not named as a whole path token.
A longer sibling such as ``example.py.bak`` contains ``example.py`` as a
prefix substring; that is not a disposition of the shorter file
(CWE-1288; MITRE, 2026). ``path:line`` still counts. `valid_control`
rejects APPROVE when that tuple is non-empty, both before and after
bounded-evidence repair. Developer experience / User experience
section labels were already required; this change only closes the file-walk
hole.

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

## Rollback

Remove the `unnamed_changed_files` checks from the two APPROVE blocks and
the helper. Existing “at least one file” detection remains.

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
