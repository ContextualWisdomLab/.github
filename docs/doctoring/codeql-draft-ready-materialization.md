# CodeQL draft-to-Ready materialization

Date: 2026-10-01

## Failure scene

Organization ruleset consumers launch the central required workflows for
`opened`, `synchronize`, and `reopened`, but do not launch another run when an
unchanged pull-request head moves from Draft to Ready. The central CodeQL
entry job used the event's Draft snapshot as a job-level runner guard and
assumed `ready_for_review` would re-run the same head. Live unchanged-head
canaries in `ContextualWisdomLab/Orgmetra` disproved that assumption: CodeQL
remained skipped after Ready.

## Decision

CodeQL now materializes exact-head security evidence for both Draft and Ready
pull requests. Only `closed` remains a job-level exclusion. This does not
admit a pull request for review, publish a review verdict, weaken a CodeQL
finding, or promote predecessor evidence. The existing live repository,
pull-request number, head, base, merge source, required run, authenticated
status, GHAS identity, and SARIF checks remain unchanged.

Model-backed review workflows keep their Draft exclusion because Ready is the
review-admission boundary. Their missing Ready materialization remains tracked
separately; running a model review while a pull request is Draft would hide the
actual event-delivery defect rather than repair it.

## Alternatives rejected

- Rely on `ready_for_review`: ruleset consumers do not receive that event.
- Re-run a skipped Draft job manually: a no-op rerun keeps the same Draft event
  snapshot and is not durable policy.
- Review Draft pull requests: violates the review-admission contract.
- Manufacture a success status: discards the authenticated CodeQL/SARIF proof.

## Evidence and follow-up

`tests/test_control_workflows_skip_draft_prs.py` now separates security-scan
materialization from review admission. The RED fixture reproduced the Draft
guard in `detect-languages`; GREEN requires exactly the closed-event guard and
forbids a Draft predicate there. The warnings-fatal focused CodeQL and
runner-admission suite passes 52 tests. The complete warnings-fatal suite
reached 5,135 passes, 8 skips, and 40 subtests but retained 25 protected-main
failures caused by unclosed test/production `HTTPError` fixtures and existing
review-preflight cases; representative failures reproduce unchanged on clean
protected `main@37b10243cec3d160ecc9c1be75c71428b160a703`. Those failures are
not promoted as GREEN evidence for this repair.

Post-merge evidence is a new or synchronized Draft consumer head that reaches
terminal CodeQL dispatch evidence without a Ready transition. Review
materialization must still be repaired at the central review owner before
unchanged-head Ready can be treated as sufficient to request OpenCode, Strix,
or Noema.
