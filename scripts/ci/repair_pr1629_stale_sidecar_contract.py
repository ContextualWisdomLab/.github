#!/usr/bin/env python3
"""Repair stale PR #1629 sidecar policy assertions, then self-delete via CI."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "tests/test_contextual_orchestrator_review_sidecar_contract.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace exactly one expected stale contract fragment."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    """Align the older sidecar contract test with the central free-only boundary."""
    text = TARGET.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "fail-closed zero-cost pool (prioritized by the ZDR policy in\n",
        "fail-closed zero-cost pool (governed by the ZDR policy in\n",
        "module policy wording",
    )
    text = replace_once(
        text,
        '    assert \'parser.add_argument("--pool", choices=("free", "auto"), default="free")\' in text\n',
        '    assert \'parser.add_argument("--pool", choices=("free",), default="free")\' in text\n'
        '    assert \'choices=("free", "auto")\' not in text\n',
        "free-only parser assertion",
    )
    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
