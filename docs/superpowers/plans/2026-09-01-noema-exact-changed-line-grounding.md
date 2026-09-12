# Noema Exact Changed-Line Grounding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Noema's exact changed-side validator fail-closed while giving both the first LLM request and its one repair retry an authoritative, compact coordinate manifest.

**Architecture:** Parse the bounded unified diff once, group exact `(path, line, side)` locations by file and side, and encode consecutive lines as inclusive ranges in compact JSON. Put that manifest in the prompt as the sole authority for `reviewed_lines`, adversarial probes, and finding coordinates; retain the existing deterministic post-response validator unchanged.

**Tech Stack:** Python 3.14, pytest, GitHub Actions, OpenAI-compatible chat-completion transport.

**Spec:** Live incident `ContextualWisdomLab/bandscope#1122`, Actions job `99792663163` (`Noema reviewed line 3 is not an exact changed-side line`).

## Global Constraints

- Do not coerce, snap, filter, or silently discard invalid model coordinates.
- Do not downgrade a formal verdict to a comment to obtain a green check.
- Keep retry count, reviewer identity, provider routing, merge authority, and current-head validation unchanged.
- The manifest must be deterministic, UTF-8 safe, and compact enough not to duplicate every changed line as a JSON object.

---

### Task 1: Reproduce the ungrounded retry

**Files:**
- Test: `tests/test_noema_review_gate.py`

**Interfaces:**
- Consumes: `changed_diff_locations()` and `call_llm()`.
- Produces: regressions for range compression and for manifest presence on both initial and repair requests.

- [ ] Add a mixed LEFT/RIGHT multi-file diff fixture and exact manifest expectation.
- [ ] Add a two-response LLM fixture whose first verdict fails specifically at reviewed-line item 3.
- [ ] Run the focused test before implementation and require the expected missing-interface failure.

### Task 2: Ground formal review coordinates

**Files:**
- Modify: `scripts/ci/noema_review_gate.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `_compact_line_ranges(lines: Sequence[int]) -> str` and `changed_line_manifest(locations: Sequence[tuple[str, int, str]]) -> str`.

- [ ] Compress sorted line numbers into inclusive ranges.
- [ ] Serialize one deterministic JSON entry per path with only populated LEFT/RIGHT sides.
- [ ] Include the authoritative manifest in every request and point repair guidance at it.
- [ ] Leave `validate_substantive_verdict()` unchanged.

### Task 3: Verify and publish

**Files:**
- Remove: `.github/workflows/noema-coordinate-grounding-writer.yml`
- Remove: `scripts/ci/_temporary_apply_noema_coordinate_grounding.py`

- [ ] Run the focused RED test and confirm the expected failure.
- [ ] Run the focused Noema suite after implementation.
- [ ] Run the full pytest/coverage/docstring/compile/diff gates.
- [ ] Preserve separate test-first and implementation commits and remove one-shot writer files.
