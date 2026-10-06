# OpenCode peer-check fallback reevaluation

Status: Proposed. Owner issue: #2125.

Protected main `fb17ef556f94f673234aa557254ae52779e9a7b0` accepted a
current-head CHANGES_REQUESTED review carrying its canonical model-unavailable
fallback marker as a substantive receipt. The required caller consequently
skipped another review after peer CodeQL checks recovered (#2113,
job 103581933696).

The receipt helper matches the complete canonical failed-peer-check payload:
fixed producer prose, the current head SHA, failed-check rows, and an optional
generated Mermaid evidence map. Extra prose, mixed findings, and unknown formats
remain formal blockers; a heading or fallback marker cannot remove a product
finding. A diagram heading alone cannot hide additional prose. A newer fallback blocks reuse of an older same-head
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

## Unstructured finding regression

The db8058e9 test exposes a product finding appended as ordinary prose beneath
the canonical heading. The former heading-only classifier discarded it. The
replacement matches the full producer envelope and fails closed on added prose,
including text after the diagram. Tests execute the actual producer printf block
and the graph emitter rather than reproducing shortened synthetic envelopes.
Receipt-module validation: 25 passed, 100% statements and branches; hosted
review and deployment evidence remain outstanding.

## Exact historical coverage-only refresh (#2125 / #2126)

The authenticated public review `5301203359` is preserved byte-for-byte in
`tests/fixtures/opencode_legacy_coverage_review5301203359.json`. Its historical
producer is `e6334e2` (`opencode_review_surfaces.py` and the dispatch publisher).
It contains the complete changed-file walkthrough, generated behavior graph,
fixed no-product-finding prose, exact head/run/attempt identity, failed coverage,
fixed review outcome, and appended evidence map. Protected production now posts
this fallback as COMMENT; this repair does not alter publication or workflows.

`opencode_legacy_coverage_fallback.py` shares exact classification between the
receipt helper and scheduler retry predicate. It requires an existing trusted
OpenCode login, matching full commit/body/current head, and positive decimal run
and attempt. It reconstructs file-role labels and both graphs from bounded paths
using the producer, then compares the entire envelope. The appended map may use
the producer's ordinary or merge-conflict graph; arbitrary Mermaid nodes, changed
labels, extra prose, mixed findings, malformed identities, unsupported format or
source-root-dependent API diagrams are not exempted. No repository/head/run is
hardcoded as an exception. A bare coverage substring or no-finding sentence is
not refresh permission; the old substring-only scheduler predicate is removed.

A recognized fallback is non-substantive, not APPROVED. A newer fallback,
including COMMENTED or an incorrectly posted APPROVED envelope, prevents the
receipt gate from resurrecting an older same-head approval. A later substantive
source finding still deduplicates as a formal blocker. Existing peer-check-only
fallback recognition and its regressions are preserved.

Coverage retry still requires complete current-head coverage and Strix evidence,
no failed peers, elapsed retry floor, available history, ordinary deduplication,
admission, actor and live-head checks. Failed CodeQL stays BLOCK/WAIT without
review dispatch or merge. Independent approval, last-push approval, repository
protection and exact-head revalidation are unchanged. There is no privileged
refresh override or approve/merge authority in the classifier.

### Security Notes

Review objects and body text are untrusted input. Recognition crosses only a
classification boundary, never a network/mutation boundary: exact actor and
identity validation plus full producer reconstruction fail closed on unknown
content. Changed paths are bounded to 200 rows / 512 characters and normalized
relative components; they are labels only, never opened from the review body.
No source root is passed to the renderer. Producer validation errors return
non-classification, not permission or a gate crash. No secrets, new dependencies,
permissions, logs containing private inputs, workflow changes, dispatch/rerun,
commit/push or merge were introduced. Tests cover identity mismatch, unknown
actors, extra/mixed prose and graph injection, malformed run/attempt, stale
approval resurrection, and failed peer checks.

### Local verification scope

Initial actual-fixture RED: both receipt and scheduler cases failed (2 failed).
The first minimal GREEN passed both cases (2 passed). Additional RED cases caught
a producer-validation exception and older-approval resurrection by COMMENTED;
both were repaired fail closed. Existing scheduler gate tests now use the actual
canonical fixture and full synthetic SHA rather than abbreviated coverage prose;
no gate assertions were removed. Final targeted test counts and strict coverage
are reported by the implementing lane, not by this historical record.

This is local classification/regression evidence only. Remote integration,
independent review, hosted exact-head required checks, fresh receiver execution,
substantive current-head review and protected merge remain uncompleted gates.

## Current-head CodeRabbit graph-boundary repair (2026-10-04)

The `76ab3eb5515afdc3f1d61560ad951e34d7776e3f` receipt classifier accepted
arbitrary two-space-indented lines in a Mermaid fence, including source findings.
The shell publisher preserved any body containing the evidence-map heading.
Both defects were reproduced before changing production code: four indented
finding cases failed, and three heading/arbitrary-map preservation cases failed.
A separate non-repository-cwd fixture regression failed with FileNotFoundError
before its workflow path was anchored to `Path(__file__).resolve().parents[1]`.

Receipt recognition now reconstructs the optional fixed no-path graph with
`emit_mermaid([])` and compares it exactly, alongside the unchanged full peer
fallback envelope. The receipt API has no independently trusted changed-file,
source-root or merge-state binding. Therefore even genuine path/source-dependent
flowcharts, sequence diagrams and class diagrams remain formal blockers here;
recognizing them would require that additional trusted contract, not parsing
self-asserted labels as evidence. The no-graph canonical fallback still works.
Unknown/mixed graph findings return the newer CHANGES_REQUESTED receipt instead
of discarding it or resurrecting an older approval. The historical coverage-only
classifier and its exact-envelope tests are unchanged.

The shell publisher compares the complete terminal map against a freshly emitted
graph using its existing changed-files, source-root and merge-state inputs.
Duplicate maps, wrong bindings, bare headings, extra prose and arbitrary graphs
retain all original body content and receive an explicit noncanonical-evidence
notice plus the trusted graph. Nothing is stripped or replaced to launder a
finding into a canonical fallback. Renderer errors propagate after temporary
file cleanup; a dedicated RED regression caught the former cleanup-masked error.
Source-backed canonical class graphs and ordinary/conflict maps are preserved
only when their complete producer output matches.

### Security Notes and verification boundary

Bodies and review descriptions are data, not authority. No paths from receipt
text are opened and no source-dependent trust is inferred from Mermaid syntax.
Shell comparisons quote the literal trusted graph, preserving source prose and
findings on mismatch. No new private-body logging, secrets, dependencies,
workflow/scheduler, actor, credential, permission or protection changes occur.
The escaped fixed prefix is not labeled a ReDoS vulnerability without a repro.

Local focused production/receipt/surfaces/shell/gate suites: **649 passed** in
both ordinary and `GITHUB_ACTIONS=true` environments. The receipt suite also
reported **31 passed** when launched from a real non-repository scratch cwd.
Receipt statements and branches: **100%** (160 statements, 66 branches, zero
misses). Ruff, interrogate 100%, bash syntax, Python compilation and diff checks
passed; the added-line static secret/injection/eval/deserialization scan found
no matches. These are bounded local results, not hosted review or merge approval.
The full 5,000-plus suite is reserved for the parent lane. Independent approval,
exact-head required hosted checks, fresh receiver/formal review and protected
merge remain outstanding; no commit, push, thread resolution or remote mutation
was performed by this repair lane.
