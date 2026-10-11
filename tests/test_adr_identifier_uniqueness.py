"""Contracts for unambiguous architecture decision record identifiers."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
ADR_DIRECTORY = ROOT / "docs" / "adr"
ADR_FILE_ID = re.compile(r"(?:^|[-_])(?P<identifier>\d{4})(?:[-_]|$)")


def test_adr_file_identifiers_are_unique() -> None:
    """Each numeric ADR identifier must name exactly one decision record."""
    records_by_identifier: dict[str, list[str]] = defaultdict(list)

    for path in sorted(ADR_DIRECTORY.glob("*.md")):
        match = ADR_FILE_ID.search(path.stem)
        if match is not None:
            records_by_identifier[match.group("identifier")].append(path.name)

    duplicates = {
        identifier: records
        for identifier, records in records_by_identifier.items()
        if len(records) > 1
    }

    assert duplicates == {}, f"duplicate ADR identifiers: {duplicates}"
