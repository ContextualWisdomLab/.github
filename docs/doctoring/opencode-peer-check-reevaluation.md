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
