"""Regression tests for bounded Noema changed-location prompt context."""

import json

from scripts.ci import noema_review_gate as noema
from tests.test_noema_review_gate import make_pr


def test_call_llm_reports_allowed_location_truncation(monkeypatch, capsys):
    """Report when the prompt receives only a bounded subset of changed lines."""
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example.test/chat")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "secret")
    monkeypatch.setattr(noema, "validate_substantive_verdict", lambda *_args: None)
    monkeypatch.setattr(
        noema,
        "changed_diff_locations",
        lambda _diff: {
            (f"src/{prefix}.py", line, "RIGHT")
            for prefix in ("a", "z")
            for line in range(1, 500)
        },
    )

    class Response:
        """Deterministic context-managed gateway response for this regression."""

        def __enter__(self):
            """Return this response to the context-managed caller."""
            return self

        def __exit__(self, *args):
            """Propagate exceptions raised while processing the response."""
            return False

        def read(self):
            """Return a valid non-blocking Noema verdict as encoded JSON."""
            return json.dumps(
                {
                    "choices": [{
                        "message": {
                            "content": '{"decision":"comment","summary":"checked","findings":[]}'
                        }
                    }]
                }
            ).encode()

    class Opener:
        """Return the deterministic response without making network I/O."""

        def open(self, request):
            """Discard the prepared request and return the fixture response."""
            del request
            return Response()

    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *_args: Opener())

    noema.call_llm("owner/repo", 1, make_pr(), "diff", False, "head")

    output = capsys.readouterr().out
    assert "::warning::Noema changed-location context truncated" in output
    assert "total_locations=998" in output
    assert "retained_locations=" in output
    assert "total_paths=2" in output
    assert "retained_paths=2" in output


def _long_path_locations(prefix: str, count: int) -> list[tuple[str, int, str]]:
    """Build budget-sized locations whose paths sort under one prefix."""
    return [
        (f"src/{prefix}-{'가' * 80}.py", index + 1, "RIGHT") for index in range(count)
    ]


def test_truncation_keeps_alphabetically_last_paths() -> None:
    """Truncation must degrade evenly instead of starving last-sorted paths."""
    ordered = sorted(
        _long_path_locations("a", 400) + _long_path_locations("z", 400)
    )
    interleaved = noema._interleave_locations_by_path(ordered)

    plain = json.loads(noema._bounded_allowed_locations_json([
        {"path": path, "line": line, "side": side}
        for path, line, side in ordered
    ]))
    fair = json.loads(noema._bounded_allowed_locations_json([
        {"path": path, "line": line, "side": side}
        for path, line, side in interleaved
    ]))

    assert plain["truncated"] is True
    assert fair["truncated"] is True
    assert {loc["path"] for loc in plain["locations"]} == {
        f"src/a-{'가' * 80}.py"
    }
    assert {loc["path"] for loc in fair["locations"]} == {
        f"src/a-{'가' * 80}.py",
        f"src/z-{'가' * 80}.py",
    }


def test_interleave_preserves_single_path_order() -> None:
    """One path interleaves to itself, keeping existing order contracts."""
    ordered = [("tool.py", 292, "LEFT"), ("tool.py", 295, "RIGHT")]
    assert noema._interleave_locations_by_path(ordered) == ordered


def test_interleave_preserves_uneven_path_groups() -> None:
    """A short path is emitted once while a longer path keeps its order."""
    ordered = [
        ("a.py", 1, "RIGHT"),
        ("a.py", 2, "RIGHT"),
        ("a.py", 3, "RIGHT"),
        ("z.py", 8, "RIGHT"),
    ]
    assert noema._interleave_locations_by_path(ordered) == [
        ("a.py", 1, "RIGHT"),
        ("z.py", 8, "RIGHT"),
        ("a.py", 2, "RIGHT"),
        ("a.py", 3, "RIGHT"),
    ]
