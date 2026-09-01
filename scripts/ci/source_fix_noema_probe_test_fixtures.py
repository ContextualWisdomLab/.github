#!/usr/bin/env python3
"""One-shot migration of review fixtures and stale free-pool test inputs."""

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
    """Add one ordered probe kind before each successive hypothesis field."""
    start, end = function_span(text, name)
    block = text[start:end]
    needle = '                    "hypothesis": '
    if block.count(needle) < len(kinds):
        raise SystemExit(f"{name}: expected at least {len(kinds)} multiline probes")
    cursor = 0
    for kind in kinds:
        position = block.find(needle, cursor)
        if position < 0:
            raise SystemExit(f"{name}: could not locate the next multiline probe")
        insertion = f'                    "probe_kind": "{kind}",\n'
        block = block[:position] + insertion + block[position:]
        cursor = position + len(insertion) + len(needle)
    return text[:start] + block + text[end:]


def replace_in_function(text: str, name: str, old: str, new: str) -> str:
    """Replace one exact fragment inside a named test function."""
    start, end = function_span(text, name)
    block = text[start:end]
    count = block.count(old)
    if count != 1:
        raise SystemExit(f"{name}: expected one stale fixture fragment, found {count}")
    block = block.replace(old, new, 1)
    return text[:start] + block + text[end:]


def migrate_noema_verdict_fixtures() -> None:
    """Migrate existing successful Noema verdict fixtures to probe classes."""
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


def repair_free_pool_test_inputs() -> None:
    """Align stale generic catalog fixtures with the merged free-pool source contract."""
    path = Path("tests/test_contextual_orchestrator_review_policy.py")
    text = path.read_text(encoding="utf-8")
    text = replace_in_function(
        text,
        "test_build_catalog_applies_account_cap",
        '{"provider": "openai", "model": f"o{i}", "agent_id": f"oa_{i}", "is_free": True, **FREE_PRICE}',
        '{"provider": "openrouter", "model": f"o{i}", "agent_id": f"or_{i}", "is_free": True, **FREE_PRICE}',
    )
    text = replace_in_function(
        text,
        "test_build_catalog_applies_account_cap",
        'assert account_counts["openai"] == 2',
        'assert account_counts["openrouter"] == 2',
    )
    text = replace_in_function(
        text,
        "test_build_catalog_respects_limit",
        '{"provider": "openai", "model": f"m{i}", "agent_id": f"oa_{i}", "is_free": True, **FREE_PRICE}',
        '{"provider": "openrouter", "model": f"m{i}", "agent_id": f"or_{i}", "is_free": True, **FREE_PRICE}',
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    """Apply every temporary fixture migration required by the exact base."""
    migrate_noema_verdict_fixtures()
    repair_free_pool_test_inputs()


if __name__ == "__main__":
    main()
