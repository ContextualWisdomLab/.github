#!/usr/bin/env python3
"""Repair the transient PR 787 transformer before executing it."""

from __future__ import annotations

from pathlib import Path

TARGET = Path(__file__).with_name("finalize_pr787_review_findings.py")

OLD_REPLACE_ONCE = '''def replace_once(path: str, old: str, new: str) -> None:
    """Replace exactly one literal block and fail on an unexpected source tree."""

    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement target, found {count}")
    write(path, content.replace(old, new, 1))
'''

NEW_REPLACE_ONCE = '''def _indented(block: str, width: int) -> str:
    """Return ``block`` with one uniform source indentation prefix."""

    prefix = " " * width
    return "\\n".join(prefix + line if line else line for line in block.split("\\n"))


def replace_once(path: str, old: str, new: str) -> None:
    """Replace one literal block, accepting its repository indentation."""

    content = read(path)
    matches: list[tuple[str, str]] = []
    for width in range(0, 21):
        candidate = _indented(old, width)
        count = content.count(candidate)
        if count > 1:
            raise RuntimeError(
                f"{path}: replacement target is ambiguous at indent {width}: {count}"
            )
        if count == 1:
            matches.append((candidate, _indented(new, width)))
    if len(matches) != 1:
        raise RuntimeError(
            f"{path}: expected one indentation-aware replacement target, found {len(matches)}"
        )
    candidate, replacement = matches[0]
    write(path, content.replace(candidate, replacement, 1))
'''

OLD_REPLACE_BETWEEN = '''def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    """Replace one section delimited by stable function markers."""

    content = read(path)
    start_index = content.index(start)
    end_index = content.index(end, start_index)
    write(path, content[:start_index] + replacement.rstrip() + "\\n\\n" + content[end_index + 1 :])
'''

NEW_REPLACE_BETWEEN = '''def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    """Replace one section delimited by stable function markers."""

    content = read(path)
    start_index = content.index(start)
    try:
        end_index = content.index(end, start_index)
    except ValueError:
        if not end.endswith("(\\n"):
            raise
        end_index = content.index(end[:-1], start_index)
    write(path, content[:start_index] + replacement.rstrip() + "\\n\\n" + content[end_index + 1 :])
'''

OLD_OUTPUT_REPLACEMENT = '''    if old_output not in content:
        raise RuntimeError("agent-mention-router.yml: token output block changed")
    content = content.replace(old_output, new_output, 1)
'''

NEW_OUTPUT_REPLACEMENT = '''    output_matches = [
        (_indented(old_output, width), _indented(new_output, width))
        for width in range(0, 21)
        if content.count(_indented(old_output, width)) == 1
    ]
    if len(output_matches) != 1:
        raise RuntimeError(
            "agent-mention-router.yml: token output block changed or ambiguous"
        )
    content = content.replace(*output_matches[0], 1)
'''

OLD_STEP_REPLACEMENT = '''    if old_step not in content:
        raise RuntimeError("agent-mention-router.yml: sweep step changed")
    write(path, content.replace(old_step, new_step, 1))
'''

NEW_STEP_REPLACEMENT = '''    step_matches = [
        (_indented(old_step, width), _indented(new_step, width))
        for width in range(0, 21)
        if content.count(_indented(old_step, width)) == 1
    ]
    if len(step_matches) != 1:
        raise RuntimeError(
            "agent-mention-router.yml: sweep step changed or ambiguous"
        )
    write(path, content.replace(*step_matches[0], 1))
'''

OLD_HANDLE_STATUS = '''                status_parts: list[str] = []
                if handles:
                    status_parts.append(f"Queued {' and '.join(handles)}")
                existing_handles = tuple(
'''

NEW_HANDLE_STATUS = '''                status_parts = [f"Queued {' and '.join(handles)}"]
                existing_handles = tuple(
'''

OLD_RUN_INVENTORY = '''                            "workflow_runs": [
                                {
                                    "id": 1,
                                    "event": "repository_dispatch",
                                    "display_title": f"run {noema_marker}",
                                }
                            ]
'''

NEW_RUN_INVENTORY = '''                            "workflow_runs": [
                                {
                                    "id": 0,
                                    "event": "repository_dispatch",
                                    "display_title": f"ignored {noema_marker}",
                                },
                                {
                                    "id": 1,
                                    "event": "repository_dispatch",
                                    "display_title": f"run {noema_marker}",
                                },
                            ]
'''

OLD_SWEEP_TEST_ANCHOR = '''                assert sweep.flatten_pages([{"number": 1}]) == [{"number": 1}]


            def test_repository_failure_is_isolated_and_later_repository_runs() -> None:
'''

NEW_SWEEP_TEST_ANCHOR = '''                assert sweep.flatten_pages([{"number": 1}]) == [{"number": 1}]


            def test_pull_pagination_stops_on_empty_followup_page() -> None:
                """A full page followed by an empty page terminates without page three."""

                sweep = module()
                recent = [pull(number) for number in range(1, 101)]
                client = PagingClient(
                    {
                        ("orgs/ContextualWisdomLab/repos", 1): [[repository("example")]],
                        ("repos/ContextualWisdomLab/example/pulls", 1): recent,
                        ("repos/ContextualWisdomLab/example/pulls", 2): [],
                    }
                )
                results = list(
                    sweep.list_recent_pull_requests(
                        client,
                        organization="ContextualWisdomLab",
                        repository_source="organization",
                        since="2026-08-05T00:00:00Z",
                    )
                )
                assert len(results) == 100
                pull_calls = [
                    args for args in client.calls if args[0].endswith("/pulls")
                ]
                assert len(pull_calls) == 2
                assert any("page=2" in args for args in pull_calls)
                assert not any("page=3" in args for args in pull_calls)


            def test_invalid_pull_number_fails_closed_without_error_sink() -> None:
                """Malformed pull metadata raises when no isolation sink is supplied."""

                sweep = module()
                client = PagingClient(
                    {
                        ("orgs/ContextualWisdomLab/repos", 1): [[repository("example")]],
                        ("repos/ContextualWisdomLab/example/pulls", 1): [pull(0)],
                    }
                )
                with pytest.raises(ValueError, match="invalid pull request number"):
                    list(
                        sweep.list_recent_pull_requests(
                            client,
                            organization="ContextualWisdomLab",
                            repository_source="organization",
                            since="2026-08-05T00:00:00Z",
                        )
                    )


            def test_repository_failure_is_isolated_and_later_repository_runs() -> None:
'''

RAW_TEST_HEADINGS = (
    '"""Coverage-only regressions for the review-fix scheduler."""',
    '"""Static contracts for downstream review-agent invocation idempotency."""',
    '"""Review-driven runtime regressions for the agent mention control plane."""',
    '"""Review-driven pagination and failure-isolation regressions."""',
)

RAW_GENERATED_FUNCTIONS = (
    "def dispatch_request(",
)


def main() -> int:
    """Patch matching, generated literals, and nested regex escaping."""

    content = TARGET.read_text(encoding="utf-8")
    replacements = (
        (
            OLD_REPLACE_ONCE,
            NEW_REPLACE_ONCE,
            "transient replace_once source no longer matches its contract",
        ),
        (
            OLD_REPLACE_BETWEEN,
            NEW_REPLACE_BETWEEN,
            "transient replace_between source no longer matches its contract",
        ),
        (
            OLD_OUTPUT_REPLACEMENT,
            NEW_OUTPUT_REPLACEMENT,
            "transient output replacement source no longer matches its contract",
        ),
        (
            OLD_STEP_REPLACEMENT,
            NEW_STEP_REPLACEMENT,
            "transient step replacement source no longer matches its contract",
        ),
        (
            OLD_HANDLE_STATUS,
            NEW_HANDLE_STATUS,
            "generated status block no longer matches its contract",
        ),
        (
            OLD_RUN_INVENTORY,
            NEW_RUN_INVENTORY,
            "generated workflow-run test inventory no longer matches",
        ),
        (
            OLD_SWEEP_TEST_ANCHOR,
            NEW_SWEEP_TEST_ANCHOR,
            "generated sweep coverage anchor no longer matches",
        ),
    )
    for old, new, error in replacements:
        if content.count(old) != 1:
            raise RuntimeError(error)
        content = content.replace(old, new, 1)
    for heading in RAW_TEST_HEADINGS:
        old = "dedent(\n            '''\n            " + heading
        new = "dedent(\n            r'''\n            " + heading
        if content.count(old) != 1:
            raise RuntimeError(f"generated test block no longer matches: {heading}")
        content = content.replace(old, new, 1)
    for signature in RAW_GENERATED_FUNCTIONS:
        old = "dedent(\n            '''\n            " + signature
        new = "dedent(\n            r'''\n            " + signature
        if content.count(old) != 1:
            raise RuntimeError(
                f"generated function block no longer matches: {signature}"
            )
        content = content.replace(old, new, 1)
    for overescaped, corrected in (
        (r"\\\\d", r"\\d"),
        (r"\\\\[", r"\\["),
        (r"\\\\]", r"\\]"),
    ):
        content = content.replace(overescaped, corrected)
    TARGET.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
