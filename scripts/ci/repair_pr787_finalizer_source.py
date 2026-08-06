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


def main() -> int:
    """Patch matching and nested regex escaping deterministically."""

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
    )
    for old, new, error in replacements:
        if content.count(old) != 1:
            raise RuntimeError(error)
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
