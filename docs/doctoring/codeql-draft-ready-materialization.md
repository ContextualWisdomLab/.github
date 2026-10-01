# CodeQL Draft event materialization

Date: 2026-10-01

## Failure scene

Organization ruleset consumers launch the central required workflows for
`opened`, `synchronize`, and `reopened`, but do not launch another run when an
unchanged pull-request head moves from Draft to Ready. The central CodeQL
entry job used the event's Draft snapshot as a blanket job-level runner guard
and assumed `ready_for_review` would re-run the same head. Live unchanged-head
canaries in `ContextualWisdomLab/Orgmetra` disproved that assumption: CodeQL
remained skipped after Ready.

A second live failure mode existed at the owner: a `converted_to_draft` event
must enter the same per-PR concurrency group to retire stale Ready work, but it
must not start a replacement scan. Treating every Draft event identically
cannot satisfy both obligations.

## Decision

CodeQL uses an explicit event and repository matrix:

- consumer `opened`, `synchronize`, and `reopened` Draft events materialize
  exact-head security evidence;
- the native `ContextualWisdomLab/.github` owner skips Draft entry jobs to
  preserve runner capacity;
- `converted_to_draft` and `closed` enter workflow concurrency but skip the
  entry job, retiring stale same-PR work without a new scan;
- Ready heads continue through the existing scan path.

This does not admit a pull request for review, publish a review verdict,
weaken a CodeQL finding, or promote predecessor evidence. The existing live
repository, pull-request number, head, base, merge source, required run,
authenticated status, GHAS identity, and SARIF checks remain unchanged.

Model-backed review workflows keep their Draft exclusion because Ready is the
review-admission boundary. Their missing Ready materialization remains tracked
separately; running a model review while a pull request is Draft would hide the
actual event-delivery defect rather than repair it.

## Alternatives rejected

- Rely on `ready_for_review`: ruleset consumers do not receive that event.
- Scan every Draft event: native-owner Drafts consume scarce control runners,
  and `converted_to_draft` would replace rather than merely retire work.
- Skip every Draft event: consumer heads can remain permanently without
  CodeQL evidence.
- Re-run a skipped Draft job manually: the event snapshot remains Draft and
  the policy defect survives.
- Manufacture a success status: discards authenticated CodeQL/SARIF proof.

## Evidence and follow-up

The RED contract produced two failures against the blanket Draft guard: it
rejected missing consumer materialization and missing conversion-event
retirement. GREEN requires the complete repository/event matrix and keeps the
per-PR concurrency key unchanged. The focused Draft-control and queue suite
passes 86 tests; the warnings-fatal repository suite passes 5,261 tests, five
optional-platform skips, and 40 subtests. Hosted exact-head Checks remain
mandatory before protected integration.

Post-merge evidence is a new or synchronized Draft consumer head that reaches
terminal CodeQL dispatch evidence without a Ready transition, plus a native
owner Draft conversion that retires the prior run without assigning a runner.
Review materialization remains an open central-owner Gap.
