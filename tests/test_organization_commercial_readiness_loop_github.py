from __future__ import annotations

import base64
from typing import Any

import pytest

from organization_commercial_readiness_fixtures import repository_payload
from scripts.ci.organization_commercial_readiness_loop import (
    GitHubClient,
    GitHubError,
    SnapshotChanged,
)


def test_client_requires_explicit_token_and_decodes_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Organization access never falls back and JSON/empty/error responses stay distinct."""
    with pytest.raises(GitHubError, match="GH_TOKEN"):
        GitHubClient("")
    with pytest.raises(GitHubError, match="GH_TOKEN"):
        GitHubClient.from_environment({})
    assert isinstance(GitHubClient.from_environment({"GH_TOKEN": " token "}), GitHubClient)
    monkeypatch.setenv("GH_TOKEN", "live")
    assert isinstance(GitHubClient.from_environment(), GitHubClient)

    class Completed:
        def __init__(self, code: int, out: str = "", err: str = "") -> None:
            self.returncode, self.stdout, self.stderr = code, out, err

    responses = [Completed(0, '{"ok":true}'), Completed(0), Completed(1, err="x" * 2000)]
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: Any) -> Completed:
        calls.append(args)
        assert kwargs["env"]["GH_TOKEN"] == "token"  # noqa: S105
        return responses.pop(0)

    monkeypatch.setattr("subprocess.run", fake_run)
    client = GitHubClient("token")
    assert client.request("/ok") == {"ok": True}
    assert client.request("/empty", method="POST", payload={"a": 1}) is None
    with pytest.raises(GitHubError) as error:
        client.request("/fail")
    assert len(str(error.value)) < 1200
    assert calls[1][:4] == ["gh", "api", "--method", "POST"]


def test_client_transport_and_invalid_json_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transport and JSON failures never become empty successful evidence."""
    client = GitHubClient("secret")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("network")),
    )
    with pytest.raises(GitHubError, match="transport failed"):
        client.request("/transport")

    class Completed:
        returncode, stdout, stderr = 0, "not-json", ""

    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: Completed())
    with pytest.raises(GitHubError, match="invalid JSON"):
        client.request("/invalid")


def test_repository_pagination_and_default_sha_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fleet discovery spans pages and exact default evidence is mandatory."""
    client = GitHubClient("token")
    pages = [
        [repository_payload(f"repo-{index}") for index in range(100)],
        [repository_payload("last")],
    ]
    monkeypatch.setattr(client, "request", lambda _path: pages.pop(0))
    assert len(client.list_repositories("ContextualWisdomLab")) == 101
    monkeypatch.setattr(client, "request", lambda _path: {"sha": "bad"})
    with pytest.raises(GitHubError, match="invalid default-branch SHA"):
        client.default_branch_sha("ContextualWisdomLab/example", "release/v1")


def test_workflow_source_materialization_and_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exact workflow source is decoded while unsafe source shapes remain unreadable."""
    client = GitHubClient("token")
    page = [
        {
            "id": index + 1,
            "name": "Hourly Product Development",
            "path": "" if index == 0 else "dynamic/x" if index == 1 else f".github/workflows/{index}.yml",
            "state": "active",
        }
        for index in range(100)
    ]
    workflow_calls = 0

    def fake(path: str, *, method: str = "GET", payload: Any = None) -> Any:
        nonlocal workflow_calls
        del method, payload
        if "actions/workflows" in path:
            workflow_calls += 1
            return {"workflows": page if workflow_calls == 1 else []}
        if "/contents/" in path:
            index = int(path.split("/")[-1].split(".")[0])
            if index == 2:
                data = b"on:\n  workflow_dispatch:\n"
                return {
                    "type": "file",
                    "size": len(data),
                    "sha": "good",
                    "encoding": "base64",
                    "content": base64.b64encode(data).decode(),
                }
            if index == 8:
                raise GitHubError("forbidden")
            variants: list[Any] = [
                None,
                {"type": "dir", "size": 0, "encoding": "base64"},
                {"type": "file", "size": 1_048_577, "encoding": "base64"},
                {"type": "file", "size": 1, "encoding": "utf-8"},
                {"type": "file", "size": 1, "encoding": "base64", "content": "%%%"},
                {"type": "file", "size": 1, "encoding": "base64", "content": "/w=="},
            ]
            return variants[(index - 3) % len(variants)]
        raise AssertionError(path)

    monkeypatch.setattr(client, "request", fake)
    records = client.list_workflows("ContextualWisdomLab/example", "a" * 40)
    assert len(records) == 100 and workflow_calls == 2
    assert records[2].content_sha == "good"
    assert sum(item.content is not None for item in records) == 1


def test_run_and_pull_inventories_cover_live_fields_and_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live-run and pull inventories preserve exact identity across pages."""
    client = GitHubClient("token")
    pull_calls = 0

    def fake(path: str, *, method: str = "GET", payload: Any = None) -> Any:
        nonlocal pull_calls
        del method, payload
        if "actions/runs" in path:
            status = path.split("status=")[1].split("&")[0]
            page = int(path.split("&page=")[1].split("&")[0])
            if page > 1:
                return {"workflow_runs": []}
            return {
                "workflow_runs": [{
                    "id": len(status),
                    "name": "Hourly Product Development",
                    "path": ".github/workflows/hourly-product-development.yml",
                    "status": "" if status == "queued" else status,
                    "head_sha": "a" * 40,
                }]
            }
        if "/pulls?" in path:
            pull_calls += 1
            size = 100 if pull_calls == 1 else 1
            return [{
                "number": index + 1,
                "draft": False,
                "base": {"ref": "main"},
                "head": {"sha": f"{index + 1:040x}"},
                "updated_at": "2026-08-08T00:00:00Z",
            } for index in range(size)]
        raise AssertionError(path)

    monkeypatch.setattr(client, "request", fake)
    runs = client.list_active_runs("ContextualWisdomLab/example")
    assert len(runs) == 5 and runs[0].status == "queued"
    assert len(client.list_open_pulls("ContextualWisdomLab/example")) == 101


def test_snapshot_movement_and_dispatch_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshots reject movement and dispatches retain the reviewed bounded payloads."""
    client = GitHubClient("token")
    shas = iter(("a" * 40, "b" * 40))
    monkeypatch.setattr(client, "default_branch_sha", lambda _repo, _branch: next(shas))
    monkeypatch.setattr(client, "list_workflows", lambda _repo, _ref: ())
    monkeypatch.setattr(client, "list_active_runs", lambda _repo: ())
    monkeypatch.setattr(client, "list_open_pulls", lambda _repo: ())
    with pytest.raises(SnapshotChanged):
        client.snapshot("ContextualWisdomLab/example", "main")

    calls: list[tuple[str, str, Any]] = []

    def capture(path: str, *, method: str = "GET", payload: Any = None) -> None:
        calls.append((path, method, payload))

    monkeypatch.setattr(client, "request", capture)
    client.dispatch_review_repair("ContextualWisdomLab/example", "develop")
    client.dispatch_product_workflow("ContextualWisdomLab/example", 91, "develop")
    assert calls[0][2]["client_payload"] == {
        "target_repository": "ContextualWisdomLab/example",
        "base_branch": "develop",
        "max_prs": "50",
        "max_dispatches": "1",
        "retry_hours": "1",
        "dry_run": False,
    }
    assert calls[1][2] == {"ref": "develop"}


def test_complete_snapshot_materialization(monkeypatch: pytest.MonkeyPatch) -> None:
    """One stable default head yields workflows, runs, and pull records together."""
    client = GitHubClient("token")
    monkeypatch.setattr(client, "default_branch_sha", lambda _repo, _branch: "a" * 40)
    monkeypatch.setattr(client, "list_workflows", lambda _repo, _ref: ())
    monkeypatch.setattr(client, "list_active_runs", lambda _repo: ())
    monkeypatch.setattr(client, "list_open_pulls", lambda _repo: ())
    result = client.snapshot("ContextualWisdomLab/example", "main")
    assert result.default_sha == "a" * 40


def test_default_branch_sha_normalizes_valid_hex(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid exact branch identity is normalized before fingerprinting."""
    client = GitHubClient("token")
    monkeypatch.setattr(client, "request", lambda _path: {"sha": "A" * 40})
    assert client.default_branch_sha("ContextualWisdomLab/example", "main") == "a" * 40
