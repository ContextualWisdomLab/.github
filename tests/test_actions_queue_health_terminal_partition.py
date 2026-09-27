"""Overflowing cancelled history retains complete native time partitions."""

from datetime import datetime, timezone
import json
from subprocess import CompletedProcess
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.test_actions_queue_health_post_evidence_retry import queue_health


def test_terminal_history_partitions_without_dropping_records():
    """Read over 1000 records in disjoint seconds through real pagination."""
    records = [
        {"id": n, "created_at": f"2026-09-27T00:00:0{n % 2}Z"}
        for n in range(1, 1002)
    ]
    paths = []

    def runner(args, **kwargs):
        """Honor GitHub's native inclusive time range and page filters."""
        path = args[-1]
        paths.append(path)
        query = parse_qs(urlsplit(path).query)
        selected = records
        if "created" in query:
            lower, upper = query["created"][0].split("..")
            selected = [r for r in records if lower <= r["created_at"] <= upper]
        page = int(query.get("page", ["1"])[0])
        return CompletedProcess(args, 0, json.dumps({
            "total_count": len(selected),
            "workflow_runs": selected[(page - 1) * 50:page * 50],
        }), "")

    actual = queue_health._read_terminal_runs(
        "repos/owner/repo/actions/runs?status=cancelled&event=pull_request_target&per_page=50",
        start=datetime(2026, 9, 27, tzinfo=timezone.utc),
        end=datetime(2026, 9, 27, 0, 0, 1, tzinfo=timezone.utc), runner=runner,
    )
    assert sorted(actual, key=lambda r: r["id"]) == records
    assert not any("page=21" in path for path in paths)
    assert len({path.split("&page=")[0] for path in paths}) == 3
    assert paths.count(paths[0]) == 1
    assert paths[0] + "&page=2" not in paths


def test_terminal_history_fails_closed_when_one_second_overflows():
    """No temporal partition can make a single overflowing second complete."""
    def runner(args, **kwargs):
        """Supply unique pages that never cover the declared total."""
        query = parse_qs(urlsplit(args[-1]).query)
        page = int(query.get("page", ["1"])[0])
        return CompletedProcess(args, 0, json.dumps({
            "total_count": 1001,
            "workflow_runs": [{"id": n} for n in range((page - 1) * 50 + 1, page * 50 + 1)],
        }), "")

    with pytest.raises(queue_health.QueueHealthError, match="within one second"):
        queue_health._read_terminal_runs(
            "repos/owner/repo/actions/runs?status=cancelled&per_page=50",
            start=datetime(2026, 9, 27, tzinfo=timezone.utc),
            end=datetime(2026, 9, 27, tzinfo=timezone.utc), runner=runner,
        )


@pytest.mark.parametrize("failure", ["read", "escaped", "duplicate"])
def test_terminal_partition_rejects_untrusted_or_incomplete_evidence(monkeypatch, failure):
    """Preserve API failures and reject escaped dates or repeated identities."""
    def github_json(endpoint, **kwargs):
        """Force overflow, then supply one malformed partition specimen."""
        if failure == "read":
            raise queue_health.QueueHealthError("GitHub API read failed")
        query = parse_qs(urlsplit(endpoint).query)
        if "created" not in query:
            raise queue_health.QueueHealthError("GitHub API pagination exceeds 20 pages")
        lower, _ = query["created"][0].split("..")
        return [{"id": 1, "created_at": "2030-01-01T00:00:00Z" if failure == "escaped" else lower}]

    monkeypatch.setattr(queue_health, "github_json", github_json)
    match = {"read": "read failed", "escaped": "escaped", "duplicate": "duplicate partition"}[failure]
    with pytest.raises(queue_health.QueueHealthError, match=match):
        queue_health._read_terminal_runs(
            "repos/owner/repo/actions/runs?status=cancelled&per_page=50",
            start=datetime(2026, 9, 27, tzinfo=timezone.utc),
            end=datetime(2026, 9, 27, 0, 0, 1, tzinfo=timezone.utc), runner=None,
        )
