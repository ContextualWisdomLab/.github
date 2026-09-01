#!/usr/bin/env python3
"""One-shot migration of existing Noema verdict fixtures to probe classes."""

from pathlib import Path


def function_span(text: str, name: str) -> tuple[int, int]:
    """Return the source span for one top-level test function."""
    marker = f"def {name}("
    start = text.index(marker)
    next_def = text.find("\ndef ", start + len(marker))
    next_decorated = text.find("\n@pytest", start + len(marker))
    ends = [position for position in (next_def, next_decorated) if position >= 0]
    return start, min(ends) if ends else len(text)


def add_multiline_probe_kinds(text: str, name: str, kinds: tuple[str, ...]) -> str:
    """Add ordered probe kinds to multiline probe dictionaries in one test."""
    start, end = function_span(text, name)
    block = text[start:end]
    needle = '                    "hypothesis": '
    if block.count(needle) < len(kinds):
        raise SystemExit(f"{name}: expected at least {len(kinds)} multiline probes")
    for kind in kinds:
        block = block.replace(
            needle,
            f'                    "probe_kind": "{kind}",\n{needle}',
            1,
        )
    return text[:start] + block + text[end:]


def main() -> None:
    """Migrate exact fixtures that exercise successful formal verdicts."""
    path = Path("tests/test_noema_review_gate.py")
    text = path.read_text(encoding="utf-8")
    text = add_multiline_probe_kinds(
        text,
        "test_call_llm_repairs_one_rejected_changed_line_verdict",
        ("mutable_alias", "execution_identity"),
    )
    text = add_multiline_probe_kinds(
        text,
        "test_substantive_approve_requires_exact_changed_lines_and_falsified_probes",
        ("mutable_alias", "time_of_check_time_of_use"),
    )
    text = add_multiline_probe_kinds(
        text,
        "test_substantive_verdict_rejects_non_changed_location_and_accepts_left_deletion",
        ("cross_contract",),
    )
    text = add_multiline_probe_kinds(
        text,
        "test_request_changes_requires_confirmed_probe_at_finding_location",
        ("authority_boundary", "cross_contract"),
    )

    start, end = function_span(text, "test_substantive_verdict_fail_closed_boundaries")
    block = text[start:end]
    old_first = '{"path": "tool.py", "line": 1, "side": "RIGHT", "hypothesis": "The value is false."'
    new_first = '{"path": "tool.py", "line": 1, "side": "RIGHT", "probe_kind": "mutable_alias", "hypothesis": "The value is false."'
    old_second = '{"path": "tool.py", "line": 1, "side": "RIGHT", "hypothesis": "The assignment vanished."'
    new_second = '{"path": "tool.py", "line": 1, "side": "RIGHT", "probe_kind": "execution_identity", "hypothesis": "The assignment vanished."'
    if block.count(old_first) != 1 or block.count(old_second) != 1:
        raise SystemExit("fail-closed fixture shape drifted")
    block = block.replace(old_first, new_first, 1).replace(old_second, new_second, 1)
    text = text[:start] + block + text[end:]

    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
