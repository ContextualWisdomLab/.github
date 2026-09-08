"""Filter non-actionable Gitleaks SARIF entries before code scanning upload."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def result_classifications(result: dict[str, Any]) -> set[str]:
    """Return normalized classification labels attached to a SARIF result."""
    raw_values = []
    raw_values.extend(result.get("classifications") or [])
    properties = result.get("properties")
    if isinstance(properties, dict):
        raw_values.extend(properties.get("classifications") or [])
    return {str(value).lower() for value in raw_values}


def filter_test_classified_results(sarif: dict[str, Any]) -> int:
    """Remove Gitleaks results classified as test fixtures and return the count."""
    removed = 0
    for run in sarif.get("runs") or []:
        if not isinstance(run, dict):
            continue
        results = run.get("results")
        if not isinstance(results, list):
            continue
        kept = []
        for result in results:
            if isinstance(result, dict) and "test" in result_classifications(result):
                removed += 1
                continue
            kept.append(result)
        run["results"] = kept
    return removed


def count_results(sarif: dict[str, Any]) -> int:
    """Count SARIF results across all runs."""
    total = 0
    for run in sarif.get("runs") or []:
        if isinstance(run, dict) and isinstance(run.get("results"), list):
            total += len(run["results"])
    return total


def load_sarif(path: Path) -> dict[str, Any]:
    """Load a SARIF JSON document with a visible failure reason."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"Could not read Gitleaks SARIF file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Gitleaks SARIF file {path} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"Gitleaks SARIF file {path} must contain a JSON object.")
    return value


def main(argv: list[str] | None = None) -> int:
    """Filter a Gitleaks SARIF file in place or into a separate output path."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not 1 <= len(args) <= 2:
        raise SystemExit("usage: filter_gitleaks_sarif.py INPUT.sarif [OUTPUT.sarif]")

    input_path = Path(args[0])
    output_path = Path(args[1]) if len(args) == 2 else input_path
    sarif = load_sarif(input_path)
    removed = filter_test_classified_results(sarif)
    remaining = count_results(sarif)
    output_path.write_text(json.dumps(sarif, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Filtered {removed} test-classified Gitleaks SARIF result(s); "
        f"{remaining} upload result(s) remain."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
