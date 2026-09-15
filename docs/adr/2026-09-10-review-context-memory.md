# Review-local memory and complete evidence accounting

Status: Proposed. Working ledger/CLI and OpenCode prompt integration; automatic per-agent fresh-session adapters and organization-wide deployment remain open.

## Decision

Agent-local memory and whole-request orchestration are separate controls. OpenCode, Noema and Strix need a review-owned work index even when a gateway can split requests: the agent still owns file/hunk obligations, callers/callees, unresolved findings, source receipts, and the final review decision. Contextual Orchestrator separately owns request capacity and inference continuation.

`review_memory.py` supplies a SQLite-backed ledger and bounded `memory.md` projection. The namespace includes repository, PR, exact base/head, reviewer run identity and policy revision. A launcher supplies a complete immutable source-plus-relationship inventory and its digest. A changed manifest under the same namespace is rejected. Stored inventory rows are checked against the sealed manifest so missing rows cannot silently become complete coverage.

Every reviewed or blocked observation references content-addressed evidence and finding artifacts. Reviewed observations are sealed. Blocked observations can acquire new evidence, but the complete union of earlier findings survives. The Markdown view shows counts and a bounded next-work page, not raw source or a growing transcript. Shortened display labels are not evidence; full locations remain in the ledger.

`coverage_complete` is never approval authority. The module always reports `approval_authorized=false`; trusted current-head source/probe receipts, outstanding findings, independent review and existing protected gates must still be evaluated. Omitted relationships cannot be disproven merely by marking one relationship unit reviewed; the launcher/structural reviewer must establish inventory completeness against actual source and call graphs.

## Operational contract

The CLI reads bounded JSON from stdin and exposes seed, next, record, status, memory, and paged findings. For example, a trusted launcher provisions a mode-0700 run directory and an empty mode-0600 SQLite file, then supplies:

- `identity`: repository, pr_number, base_sha, head_sha, reviewer (including run identity), policy_revision;
- `units`: unit_id, kind (`source` or `relationship`), location, source_digest;
- `inventory_digest`: digest of the authoritative complete source inventory.

Use `python3 scripts/ci/review_memory.py seed --db <private-db> --max-input-bytes <admitted-bound> --limit <page-bound>` with that JSON on stdin. Other commands use the same identity. `record` additionally takes unit_id, source_digest, evidence_refs, finding_refs and status. `memory` emits a regenerable index; do not treat edits to the emitted Markdown as database or gate mutations. No secret or raw provider reasoning belongs in either artifact.

Filesystem permission and symlink checks are necessary, not provenance attestation. The launcher must keep the store outside the untrusted checkout and provision it itself; a PR-supplied SQLite file is not safe merely because its permissions match. Deployment owns OS/process isolation, encryption, ACLs and retention. The CLI does not install a memory MCP. An MCP adapter may replace local persistence only after its actual isolation, paging, trust and lifecycle contracts are verified; avoid loading a whole shared memory graph into context.

## Implemented integration and remaining gaps

The existing `render_opencode_prompt_template.py` now appends the shared `review_partition_protocol.md` when rendering the actual `opencode-review-contract-*.md` files created by the current launcher. Generic templates stay byte-compatible; the original renderer and its four tests were reconstructed and checked against Git blob hashes before modification. No source/probe/approval rule is removed.

This is an actual prompt entrypoint, **not** a claim that fresh OpenCode sessions are now automatically scheduled. The protocol requests bounded work, persisted notes and real supported compaction/new-session actions. The launcher still needs automatic trusted inventory seeding, per-packet execution/continuation, and machine-enforced incomplete-result handling. Its legacy inline head/tail excerpt remains and must not be mistaken for full coverage.

Noema's structured one-shot client and Strix's stateful tool/stream client need separate adapters. Do not blindly cut tool/result histories, propagate full accumulated transcripts to children, or turn partial reviews into APPROVE/REQUEST_CHANGES findings. Infrastructure incompleteness requires a distinct terminal/continuation path, not invented code defects or unbounded whole-prompt retries. Hosted external reviewers have independent quota, auto-pause, and file-count limits; supplemental CWL coverage does not rewrite their internal memory or grant their approval.

Focused verification: 47 passing tests including the unchanged four renderer tests; 202/202 measured statements and 66/66 branches across the two Python production files. Tests include 84 source units plus an explicit relationship obligation, stale heads/digests, corrupt manifests, finding conservation, replay/idempotence, rollback, actual on-disk CLI restart, permission/symlink rejection and prompt integration. This is not full-repository CI or live-agent quality evidence.

## Research and Fugu boundary

Use this with the separate Contextual Orchestrator request-partitioning ADR, not as a substitute for Fugu/Conductor/TRINITY policy fixes. Relevant primary sources: https://arxiv.org/abs/2606.21228 ; https://arxiv.org/abs/2512.04695 ; https://arxiv.org/html/2512.04388v5 ; https://arxiv.org/html/2512.24601v3 ; https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents . Structured memory and external input access motivate the design; benchmark results from those systems are not transferred to CWL.

Independent review, exact-head hosted checks, published immutable owner dependencies and consumer execution are required before rollout. No new workflow, provider token, relaxed gate, direct-model bypass or production default is introduced here.
