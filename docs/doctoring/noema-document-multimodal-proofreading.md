# Noema document multimodal envelope and proofreading checklist

Issue: ContextualWisdomLab/.github#2280

## Problem

Noema's document reader extracted bounded text from `.docx`, `.hwp`, and `.hwpx`
files, but embedded figures never reached the model. A text-only success path
could omit images silently. Document PRs also lacked an explicit proofreading
contract tied to the organization's existing skills.

## Contract

1. **Extraction** — `scripts/ci/noema_review_document.py`
   - `extract_review_document_bundle()` returns `DocumentExtraction` with text,
     declared media count, and OpenAI-style multimodal parts (`text` locator +
     `image_url` data-URL per figure).
   - `extract_review_document()` remains text-only and **fails closed** when
     figures are present.
   - `ensure_figures_attached()` rejects partial or missing figure coverage.
   - Provisional leaf budget: at most eight figures, each at most 1.5 MiB.
   - DOCX figures are resolved only from internal image relationships in
     `word/_rels/document.xml.rels` and attached in the source order of
     `a:blip` elements in `word/document.xml`. Orphan ZIP media is not source
     evidence; missing, external, or out-of-bound relationship targets fail
     closed.

2. **Review gate** — `scripts/ci/noema_review_gate.py`
   - `fetch_file_review_bundle()` fetches office documents as text + parts.
   - `ReviewContext` carries bounded text and flattened multimodal parts from
     changed/removed files.
   - `call_llm()` emits a multimodal user message when parts exist; otherwise
     the legacy string envelope is preserved.
   - `document_proofreading_prompt_lines()` encodes the reused skills:
     `~/.claude/skills/humanize-korean/SKILL.md` (KO/EN style and terminology
     consistency without rewriting substance) and
     `~/.agents/skills/source-check/SKILL.md` (citation/page verification;
     no arbitrary number or citation edits).

3. **Fixtures** — synthetic archives only in `tests/test_noema_document_review_context.py`.
   Research originals and participant materials are never used.

## Ownership and delivery state

- `.github#2281` implementation evidence is the functional commit
  `4513708f47ee44b51d431272f91af753dda8a882` (tree
  `b3deea106a94799f324cee385f9246db6b443548`). The branch remains Draft and
  Proposed until fresh exact-head Checks and an independent approval exist.
- Multimodal route discovery and fail-closed capability selection belong to
  `ContextualWisdomLab/contextual-orchestrator#1203`, current head
  `79fef32bda4dd599ea973e790b09e58ed02dd9b1` (tree
  `645b468916ddb3c4437a96151c6740ab08d9f646`). Functional repair
  `429916859af201e44d6109271435de0f8d519a43` preserves the earlier endpoint
  and failover work, rejects disabled and non-chat media pools before SSE, and
  carries `input:image` into streamed realtime judging. Concurrent RED
  `718657adc70f755bc51e7b37a8a77c70c795b3df` remains in ancestry; the related
  exact-tree suite is `127 passed`. Full collection is not GREEN because of
  pre-existing `jsonschema.RefResolver` and removed embedding-lease-symbol test
  imports. The leaf must consume a protected immutable release/pin; an open
  owner PR is not a released API.
- HWPX still discovers archive media by suffix rather than from an
  authoritative section relationship/source-order mapping. Its provenance is
  therefore unresolved and remains a blocker; no HWPX completion claim is
  made by the DOCX repair.

## Verification

```bash
PYTHONWARNINGS=error python3 -m pytest -q \
  tests/test_noema_review_document_multimodal.py \
  tests/test_noema_document_review_context.py \
  tests/test_noema_removed_file_context.py
coverage run -m pytest tests && coverage report --show-missing
interrogate
```

Multimodal e2e tests assert `image_url` data-URLs in the captured LLM payload
and fail-closed behavior when figures are omitted or media types are unsupported.
The current focused evidence is `57 passed, 2 skipped`; hosted exact-head
evidence remains required after the branch is published.
