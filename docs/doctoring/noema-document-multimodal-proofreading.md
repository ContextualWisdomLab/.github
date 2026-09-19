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

## Verification

```bash
python3 -m pytest tests/test_noema_document_review_context.py -q
coverage run -m pytest tests && coverage report --show-missing
interrogate
```

Multimodal e2e tests assert `image_url` data-URLs in the captured LLM payload
and fail-closed behavior when figures are omitted or media types are unsupported.
