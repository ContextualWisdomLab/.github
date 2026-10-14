<!-- cwl-review-memory/v1 -->

For a review that cannot fit in one context, maintain a bounded `memory.md`
index outside the PR checkout. Bind it to the exact repository, PR, base/head,
reviewer run, and policy revision. Inventory every changed source slice and
explicit cross-file/relationship obligations before dividing work. Do not omit
binary, generated, deleted, or unsupported files; unresolved units stay blocked.

Read one bounded work packet at a time. Persist source/evidence digests, finding
artifact references, unresolved questions, and the next unit before compaction
or a fresh worker session. Read only the next index page on resume, not the full
transcript. Keep the complete finding union outside summaries. Revisit original
source and callers/callees when checking relationships or conflicting findings.

The trusted helper `${GITHUB_WORKSPACE}/scripts/ci/review_memory.py` provides
`seed`, `next`, `record`, `status`, `memory`, and paged `findings` operations on a
launcher-provisioned private database. A memory MCP is an alternative only when
its actual tools, namespace isolation, persistence, and permissions are verified;
do not invent MCP availability. Memory is not approval evidence.

A reset requires an actual supported compaction/new-session operation; a note
saying "start fresh" does not reset context. Oversized atomic packets require
finer semantic slicing or an explicit incomplete result, never head/tail loss.
Before the final verdict, reconcile all source and relationship units and every
finding against current-head evidence. Preserve all existing probe, execution,
independent-review, and approval gates. Missing tools or incomplete work must not
be disguised as either approval or an invented source defect.
