# Doctoring record: syncing `docs/product-goal-directive.md` with the user's current standing text (2026-09-03)

- **Date:** 2026-09-03
- **Subject:** two peer sessions this cycle independently found that at least one live `/loop`'s
  standing prompt text carried content — an i18n language list, LLM provider-group/timeout language, a
  fuller core-foundation ownership map — that `docs/product-goal-directive.md` did not have, and flagged
  the drift to the user rather than guessing at a fix. This record closes that gap with primary-source
  evidence: the user re-pasted their full current `/loop` invocation text (both the 39-item backlog and
  the nine-section "일반 지침") directly into this session, giving a verbatim, current, authoritative text
  to reconcile the file against — not a secondhand description of it.
- **Decision record:** none in `docs/adr/` — this is a content-sync correction to an existing standing
  directive, authorized in advance by the file's own header ("edit this file in place... do not fork a
  second copy elsewhere"), not a new architecture decision.
- **PR:** see the PR that carries this commit.

## Method

Diffed the user's freshly-pasted nine-section "일반 지침" text against the current
`docs/product-goal-directive.md` (as of `origin/main`) section by section, in full, looking for content
present in one but not the other in either direction — not just scanning for the specific terms the
peer sessions had already named.

## Result: six of nine sections had genuinely new content in the user's text; none had content removed

| Section | New in the pasted text, not in the file | Notes |
|---|---|---|
| §1 (execution loop) | The "PR 0개" rule is refined: only via merge or a verified successor's full delta inheritance, never a plain Close | Consistent with, and now explicitly ties to, the expanded §2 Close-vs-repair policy |
| §2 (concurrent ops) | A full Close-vs-repair policy (single-writer/DDD violations, wrong base/conflicts, ADR number collisions, premature `Accepted`, unprotected dependencies, missing test/fixture/contract = repair finding, not Close; demote to Draft/Proposed; non-force restack/retarget; successor must fully inherit delta; reopen wrongly-closed PRs; Close only for explicit user request/no valid delta/malicious change/full inheritance) plus a new permitted tool (`epoko77-ai/im-not-ai` for Korean text) | This is already this session's own established practice (every "repair, not Close" correction this cycle follows it) — the file was the one that hadn't caught up, not the practice |
| §3 (research/traceability) | An explicit decision-record completeness bar (a first-time reader must be able to reconstruct problem/constraints/alternatives/reasons/evidence/risk/effect/follow-up) | |
| §4 (UX/UI) | An explicit 8-language i18n list (한국어·영어·일본어·중국어·베트남어·스페인어·독일어·프랑스어) and a translation-storage architecture constraint (DB-versioned resource, not files/JS bundles; server/native fetch by screen key only, no full-catalog SPA assumption; per-product review/approval/deploy/rollback API + admin UI when no shared translation-management product exists) | This is exactly the "i18n language list" content the first peer session cited before self-correcting that it wasn't in the file — the content is real, it was just genuinely missing from the file, not a peer citation error as first assumed |
| §7 (verification) | An explicit `p95≤20ms` page-latency target, plus explicit prohibitions on sample-shrinking, excluding measurements, and unrealistic cache warm-up | Framed in the file as an aggressive target to profile and drive toward honestly, not an unconditional merge-blocking gate, consistent with this section's own existing verification-realism posture |
| §8 (LLM/orchestration) | Explicit null-default-timeout semantics ("Model timeout은 application·Agent·Gateway 공통 상한 없이 기본 null이다") with upstream-provider-owns-communication-failure framing, an admin-web model-management scope note, and an explicit user-cancel/provider-end/admin-timeout distinction for reasoning/streaming/tool calls | The null-timeout principle itself is already established and repeatedly enforced elsewhere this cycle (e.g. Noema's retired 900-second repair deadline); the admin-web-scoped exception was new to this file |
| §9 (reference libraries) | A much larger, explicitly-categorized "core foundation" ownership map (조직·계약 / 의미·데이터 / AI·운영 / Identity·보안·runtime / 재사용 기능) naming 15 repositories the file's existing per-repo list did not have at all (`enterprise-architecture-core`, `context-graph-contracts`, `ConceptWeave`, `semantic-data-portal`, `EmbedRelay`, `mhtml-etl-gateway`, `noema`, `pg-llm-batch`, `EgressWeave`, `OriginWeave`, `pingora-gateway`, `quarantine-sandbox-runtime`, `appguardrail`, `inkspan`, `DiagramWeave`), plus an owner/consumer boundary rule ("owner가 미성숙하거나 API가 없어도 consumer가 복제·우회하지 않는다...") not previously written into this file at all | This is exactly the "fuller core-foundation ownership map" content the first peer session cited before self-correcting — again, real content, genuinely missing from the file, not a citation error |
| §5 (architecture/DDD) | No genuinely new content found — the pasted text's DDD terminology (Aggregate/Entity/Value Object/etc.) matches the file's existing §5 in substance; the file's own wardnet-naming and DB-object-naming reconciliation notes (Devin-flagged, 2026-08-30) remain the correct resolution and were left untouched | |
| §6 (implementation language) | No genuinely new content found — Rust-preference, no-heuristics, and Python 3.14/GIL language match closely between both texts | |

## What this resolves

Both peer sessions that raised this (`contextual-orchestrator-integration-8ec7-26` with a specific,
grep-verified check of their own session's loop text; `elated-knuth-7e884a-47` with a lighter read that
found no obvious gap) were each partially right for different reasons: the *content* the first peer
described (i18n list, provider-group/timeout language, ownership map) really does exist and really was
missing from the file — their initial citation of *where* it lived in the file (§4/§8/§9's existing text)
was the error they caught and corrected, not the claim that the content existed somewhere. This record
closes the actual gap: the content now lives in this file, sourced directly from the user's own pasted
text in this session rather than reconstructed from a description of it.

## What this does not resolve

This sync captures the user's `/loop` text as pasted 2026-09-03. It is not a guarantee that every other
live session's own `/loop` prompt matches this file either now or in the future — per this file's own
"edit this file in place" instruction, whichever agent next receives updated text from the user directly
should sync it the same way, rather than let a private copy silently diverge again.

## Audit trail

- `docs/product-goal-directive.md` — the file this record documents changes to.
- The user's `/loop` invocation text pasted directly into this session, 2026-09-03 (not separately
  archived; this record's diff table is the durable summary of what it added).
- `docs/product-technical-gap-baseline.md` — cited above for the "repair, not Close" and null-timeout
  practices already independently established this cycle, now made canonical in the directive itself.
