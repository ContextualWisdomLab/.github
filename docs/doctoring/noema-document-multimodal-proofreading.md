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
   - HWPX figures are resolved from the `Contents/content.hpf` manifest and
     spine-ordered section XML `binaryItemIDRef` references. Locators preserve
     section, paragraph/run/table-cell position, manifest ID, and exact
     `BinData` path. Orphans are ignored; duplicate IDs/entries, unresolved or
     external references, traversal, malformed XML, and unreadable targets
     fail closed.

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

- `.github#2281` DOCX implementation evidence is functional commit
  `4513708f47ee44b51d431272f91af753dda8a882` (tree
  `b3deea106a94799f324cee385f9246db6b443548`). HWPX RED
  `21eae9d5e9ce4ee43ee692776a1062c13c9f1a98` precedes GREEN
  `768860076068384552c9dfdb02bec1d8996962be` (tree
  `3b8b28e6b815ec7b635458c456f0deb921a49ec8`). The branch remains Draft and
  Proposed until fresh exact-head Checks and an independent approval exist.
- Multimodal route discovery and fail-closed capability selection belong to
  `ContextualWisdomLab/contextual-orchestrator#1203`, current head
  `37435b5e82e9fe53abc67b032c67df83425c0250` (tree
  `e7bf07b644af5b3ed7b1117b0baeab14767f4ad8`). It ordinarily preserves source
  repair `738ab3689d110685ca07f09b7c51031f11d3f07f`, the prior exact evidence, and
  RED `7f69bacb0d35f00e6902df8e440efeafbe08dbe3` before its latest judge-failover
  GREEN. Its four exact-head workflows are queued and no independent approval
  exists. The leaf must consume a protected immutable release/pin; an open
  owner PR is not released API authority.

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
The current focused evidence is `79 passed, 2 skipped`; the owned document
reader is `381/381` statements and `134/134` branches (100%). Hosted exact-head
evidence remains required after the branch is published.
