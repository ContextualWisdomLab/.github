"""Keep every central OSV-Scanner Action use on one reviewed release."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OSV_ACTION_SHA = "6e4298ebc4db23e847df9b2e2de2939d6f066c67"
OSV_ACTION_TAG = "v2.5.1"
_PIN = re.compile(
    r"google/osv-scanner-action/(?P<component>"
    r"osv-scanner-action|osv-reporter-action|"
    r"\.github/workflows/osv-scanner-reusable-pr\.yml)@"
    r"(?P<sha>[^\s]+)\s+#\s+(?P<tag>v[^\s]+)"
)
_EXPECTED_COMPONENTS = Counter(
    {
        "osv-scanner-action": 4,
        "osv-reporter-action": 1,
        ".github/workflows/osv-scanner-reusable-pr.yml": 1,
    }
)


def test_all_osv_scanner_actions_share_the_reviewed_current_release() -> None:
    """Reject partial bumps, malformed refs, and stale OSV Action comments."""
    observed: set[tuple[str, str]] = set()
    components: Counter[str] = Counter()

    for path in sorted((REPO_ROOT / ".github/workflows").glob("*.yml")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "google/osv-scanner-action/" not in line:
                continue
            match = _PIN.search(line)
            assert match is not None, f"malformed OSV Action pin: {path}:{line_number}"
            observed.add((match.group("sha"), match.group("tag")))
            components[match.group("component")] += 1

    assert observed == {(OSV_ACTION_SHA, OSV_ACTION_TAG)}
    assert components == _EXPECTED_COMPONENTS
