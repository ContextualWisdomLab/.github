"""Keep every central OpenSSF Scorecard Action use on one reviewed release."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCORECARD_SHA = "2d1146689b8cda280b9bc96326124645441f03bc"
SCORECARD_TAG = "v2.4.4"
_PIN = re.compile(
    r"ossf/scorecard-action@(?P<sha>[^\s]+)\s+#\s+(?P<tag>v[^\s]+)"
)


def test_all_scorecard_actions_share_the_reviewed_current_release() -> None:
    """Reject partial bumps, malformed refs, and stale Scorecard releases."""
    observed: set[tuple[str, str]] = set()

    for path in sorted((REPO_ROOT / ".github/workflows").glob("*.y*ml")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "ossf/scorecard-action@" not in line:
                continue
            match = _PIN.search(line)
            assert match is not None, f"malformed Scorecard pin: {path}:{line_number}"
            observed.add((match.group("sha"), match.group("tag")))

    assert observed == {(SCORECARD_SHA, SCORECARD_TAG)}
