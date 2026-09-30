# Central coverage owner stack RCA

## Incident and ownership

`ContextualWisdomLab/.github#2521` owns the repository-wide Python statement
and branch coverage repair. Concurrent PRs carried valid prerequisites rather
than competing implementations: #2530 owns the hash-pinned parser inputs used
by complete test collection, and #2532 owns explicit closure of file-like
GitHub `HTTPError` responses. Both were preserved as ordinary merge parents;
neither failure was treated as a reason to discard a PR.

## Root causes

The first warning-fatal integrated run separated three causes:

1. the predecessor tree lacked parser dependencies required during collection;
2. synthetic GitHub redirect/error paths leaked response objects under Python
   3.14 and therefore failed when `ResourceWarning` was promoted to an error;
3. four central scripts retained executable paths that their tests did not
   reach, while two tests invoked a live `gh` boundary or asserted nothing.

The remaining coverage work was test-first and behavior-bound. It exercises
queue admission/cancellation, bounded repository scans, exact Git blobs,
Cargo workspace and development-lock identity, runtime receipt architecture,
release fanout limits, and Python 3.10 TOML parser fallback. The runtime archive
prescreener's final repeated count check was proven unreachable because its
earlier exact-cardinality, uniqueness, and per-archive validation already
reject every false case; only that redundant branch was removed.

## Evidence and acceptance

- RED integrated evidence: 5,196 passed, 6 skipped; 90 statements missed and
  29 partial branches across the four remaining owner modules.
- Focused release dependency evidence: 950 passed with warnings treated as
  errors.
- GREEN combined-successor evidence after re-fetching and ordinarily merging
  current #2530 and #2521 heads: 5,291 passed, 5 skipped, 40 subtests passed;
  18,729/18,729 production statements and 7,642/7,642 branches covered, with
  production Docstring coverage at 100%.
- No warning, security result, or fail-closed input validation was suppressed.

This local result is not merge authority. Acceptance requires publication to
the re-fetched #2530 successor branch without force, fresh hosted Checks bound
to that exact commit, qualifying independent review, and ordinary protected
merge. The #2521 predecessor remains open until that protected merge and
complete tree carryover are verified.
