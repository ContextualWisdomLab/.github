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


def main() -> int:
    """Patch indentation matching and nested regex escaping deterministically."""

    content = TARGET.read_text(encoding="utf-8")
    if content.count(OLD_REPLACE_ONCE) != 1:
        raise RuntimeError("transient replace_once source no longer matches its contract")
    content = content.replace(OLD_REPLACE_ONCE, NEW_REPLACE_ONCE, 1)
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
