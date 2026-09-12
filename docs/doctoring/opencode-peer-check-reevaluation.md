# OpenCode peer-check fallback reevaluation

Status: Proposed. Owner issue: #2125.

Protected main `fb17ef556f94f673234aa557254ae52779e9a7b0` accepted a
current-head CHANGES_REQUESTED review carrying its canonical model-unavailable
fallback marker as a substantive receipt. The required caller consequently
skipped another review after peer CodeQL checks recovered (#2113,
job 103581933696).

The receipt helper recognizes the exact canonical failed-peer-check overview
and sole Findings heading before permitting change-request reevaluation. Mixed
findings and unknown formats remain formal blockers; fallback markers alone
cannot remove a product finding. The next level-two section ends Findings. A newer fallback blocks reuse of an older same-head
receipt; a later substantive product finding still deduplicates normally.
Approval eligibility and downstream gates are unchanged. This does not approve
any PR or establish model availability. PR #1706 edits a separate verdict lookup
in the same caller; this repair changes only the shared receipt helper.

Regression: six fallback-marker cases failed before the change; a substantive
finding case already passed. The receipt, live-draft and required-verdict tests
exercise the shared boundary and existing caller behavior. Actual fresh receiver
execution and a formal current-head review remain deployment acceptance gates.

## Concurrent owner integration

Ordinary merge preserves both aa6150c and 96704bc7 histories. The remote
substantive-finding repair's original mixed-review case is retained as an
additional regression. Its broad heading regex is superseded by the exact
producer envelope because unknown headings must remain blockers, not silently
qualify for reevaluation. No approval criterion is relaxed.

### Historical remote-branch validation (not merged-head proof)

Regression evidence is bound to exact commits. Commit
`9cd835df682b74ead1e5306b92280da941e45040` is RED because a mixed fallback
and authorization finding returns no receipt. Commits
`7b528279720af353ba91fbff5d43384ad466bb8b` and
`f5be0fb8f21d9fad64c8576b5e980d5eeb9a1b1e` introduce and correct the
minimal finding-heading classifier. On the corrected source blob
`310f05d956382d4ba525907ccba64c633c1c2a6c` and test blob
`05955d2e2181aefe957f239d8aae8012a0ad04d9`, the receipt,
live-Draft, required-verdict, and coverage-publication suites report 86 passed;
Ruff and compileall are green. Hosted exact-head checks, independent review, and
a fresh #2113 receiver/formal review remain deployment acceptance gates.
