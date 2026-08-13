# R coverage testthat marker short-circuit

## Incident boundary

`classify_testthat_failure` may authorize R coverage deferral only when a
testthat log contains the terminal `Error: Test failures` marker **and** a
matching `[ FAIL N |` summary. The previous implementation ran
`FAIL_SUMMARY_RE.findall` first. The common marker-absent path therefore
scanned a bounded log of up to 2 MiB with a multiline regular expression
before the necessary literal condition was known to be false.

This is a cold-path cost defect. It is not a reason to change the
positive-path grammar, package-name validation, or fail-closed cardinality
checks.

## Decision

Reject `"Error: Test failures" not in text` before any summary, error-block,
or missing-package regular expression. CPython membership on `str` uses
two-way string matching and is linear in the haystack (Crochemore & Perrin,
1991; Python Software Foundation, 2026). Thompson-style regular-expression
search remains correct for the marker-present path, but it is unnecessary
work when the authorizing marker is absent (Thompson, 1968). CWE-407
records that an algorithmically heavier scan on a large input is itself a
reliability risk (MITRE Corporation, n.d.).

A marker-present log without a fail summary still returns `False`. The fast
path is a necessary-condition rejection, not an authorization shortcut.

## Verification

A permanent regression replaces `FAIL_SUMMARY_RE` with a sentinel whose
`findall` raises. A marker-absent maximum-size bounded string must return
`False` without invoking that sentinel. The existing marker-present
contracts remain unchanged.

## References

Crochemore, M., & Perrin, D. (1991). Two-way string-matching. *Journal of
the ACM, 38*(3), 651–675. https://doi.org/10.1145/116825.116845

MITRE Corporation. (n.d.). *CWE-407: Inefficient algorithmic complexity*.
CWE. Retrieved August 13, 2026, from
https://cwe.mitre.org/data/definitions/407.html

Python Software Foundation. (2026). *re — Regular expression operations*
(Python 3.14 documentation).
https://docs.python.org/3.14/library/re.html

Thompson, K. (1968). Regular expression search algorithm. *Communications
of the ACM, 11*(6), 419–422. https://doi.org/10.1145/363347.363387
