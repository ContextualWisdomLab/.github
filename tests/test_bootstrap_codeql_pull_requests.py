"""Contract tests for new-repository CodeQL pull-request bootstrap."""

from __future__ import annotations

from io import StringIO
import json
import subprocess

import pytest

from scripts.ci import bootstrap_codeql_pull_requests as bootstrap


SHA = "a" * 40


class FakeClient:
    """Record deterministic GitHub calls without network access."""

    def __init__(self, *, open_pull: bool = False, branch_exists: bool = False) -> None:
        """Configure existing bot-owned state."""
        self.open_pull = open_pull
        self.branch_exists = branch_exists
        self.calls: list[tuple[str, str, object]] = []

    def request(self, path: str, *, method: str = "GET", payload: object = None) -> object:
        """Return the minimal REST payload required by the production flow."""
        self.calls.append((method, path, payload))
        if path.endswith("/pulls?state=open&head=ContextualWisdomLab:opencode/codeql-setup"):
            return [{"number": 7}] if self.open_pull else []
        if path.endswith("/git/ref/heads/opencode/codeql-setup"):
            if self.branch_exists:
                return {"object": {"sha": SHA}}
            raise bootstrap.GitHubError("HTTP 404")
        if path.endswith("/git/ref/heads/main"):
            return {"object": {"sha": SHA}}
        if path.endswith("/contents/.github/workflows/codeql.yml"):
            return {"content": {"sha": "b" * 40}}
        if path.endswith("/pulls") and method == "POST":
            return {"number": 42}
        if path == "repos/ContextualWisdomLab/demo":
            return {"default_branch": "main"}
        if path.endswith("/git/refs"):
            return {"ref": "refs/heads/opencode/codeql-setup"}
        raise AssertionError(path)


def uncovered_payload(name: str = "demo") -> list[dict[str, object]]:
    """Return one repository without CodeQL evidence."""
    return [{
        "name": name,
        "archived": False,
        "default_setup_state": None,
        "latest_codeql_analysis": None,
    }]


def test_rendered_workflow_redetects_stacks_and_pins_every_action() -> None:
    workflow = bootstrap.render_workflow("develop")

    assert 'branches: ["develop"]' in workflow
    assert 'repos/${{ github.repository }}/languages' in workflow
    assert '"Kotlin":"java-kotlin"' in workflow
    assert '"TypeScript":"javascript-typescript"' in workflow
    assert '"Rust":"rust"' in workflow
    assert "autobuild" not in workflow
    assert "pull_request:" not in workflow
    assert "github.event.pull_request" not in workflow
    assert "github.event_name == 'push' && github.ref || github.event_name" in workflow
    assert "cancel-in-progress: true" in workflow
    assert workflow.count("@cdf488f595d80d6e07e03d4674febd5ab45fa938 # v4.37.9") == 2
    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0" in workflow


@pytest.mark.parametrize("branch", ["", "../main", "main\nother"])
def test_rendered_workflow_rejects_unsafe_default_branch(branch: str) -> None:
    with pytest.raises(ValueError):
        bootstrap.render_workflow(branch)


def test_bootstrap_creates_exact_base_branch_workflow_and_pull_request() -> None:
    client = FakeClient()

    assert bootstrap.bootstrap_repository(client, "demo") == "created-pr-42"
    create_ref = next(call for call in client.calls if call[1].endswith("/git/refs"))
    assert create_ref[2] == {"ref": "refs/heads/opencode/codeql-setup", "sha": SHA}
    content_call = next(call for call in client.calls if "/contents/" in call[1])
    content = json.loads(json.dumps(content_call[2]))
    assert content["branch"] == "opencode/codeql-setup"
    pull_call = next(call for call in client.calls if call[1].endswith("/pulls"))
    assert pull_call[2]["base"] == "main"


def test_existing_open_pull_is_idempotent() -> None:
    client = FakeClient(open_pull=True)

    assert bootstrap.bootstrap_repository(client, "demo") == "open-pr-exists"
    assert not any(method != "GET" for method, _, _ in client.calls)


def test_unmanaged_bootstrap_branch_fails_closed() -> None:
    client = FakeClient(branch_exists=True)

    with pytest.raises(bootstrap.GitHubError, match="unmanaged"):
        bootstrap.bootstrap_repository(client, "demo")


def test_empty_repository_waits_for_its_first_commit() -> None:
    client = FakeClient()
    original = client.request

    def request(path: str, **kwargs: object) -> object:
        if path == "repos/ContextualWisdomLab/demo":
            return {"default_branch": None}
        return original(path, **kwargs)

    client.request = request  # type: ignore[method-assign]
    assert bootstrap.bootstrap_repository(client, "demo") == "pending-empty-repository"


def test_load_payload_supports_file_and_stdin(tmp_path) -> None:
    payload_path = tmp_path / "coverage.json"
    payload_path.write_text(json.dumps(uncovered_payload()), encoding="utf-8")

    assert bootstrap.load_payload(payload_path, StringIO("[]")) == uncovered_payload()
    assert bootstrap.load_payload(bootstrap.Path("-"), StringIO("[]")) == []


def test_main_rejects_invalid_repository_name(monkeypatch, tmp_path, capsys) -> None:
    payload_path = tmp_path / "coverage.json"
    payload_path.write_text(json.dumps(uncovered_payload("../escape")), encoding="utf-8")
    monkeypatch.setenv("OPENCODE_APP_TOKEN", "g" + "hs_variable_length.token")

    assert bootstrap.main([str(payload_path)]) == 1
    assert "invalid repository name" in capsys.readouterr().err


def test_client_accepts_opaque_variable_length_token() -> None:
    token = "ghs_app.jwt.with.variable.length"
    assert bootstrap.GitHubClient.from_environment({"OPENCODE_APP_TOKEN": token})._token == token


def test_client_rejects_empty_token() -> None:
    with pytest.raises(bootstrap.GitHubError, match="required"):
        bootstrap.GitHubClient.from_environment({})


def test_client_request_handles_json_empty_post_and_redacted_failure(monkeypatch) -> None:
    responses = iter([
        subprocess.CompletedProcess([], 0, '{"ok":true}', ""),
        subprocess.CompletedProcess([], 0, "", ""),
        subprocess.CompletedProcess([], 1, "", "secret-token denied"),
    ])
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return next(responses)

    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    client = bootstrap.GitHubClient("secret-token")
    assert client.request("repos/o/r") == {"ok": True}
    assert client.request("repos/o/r", method="POST", payload={"x": 1}) is None
    assert calls[1][0][-4:] == ["--method", "POST", "--input", "-"]
    assert calls[1][1]["input"] == '{"x":1}'
    with pytest.raises(bootstrap.GitHubError, match=r"\[REDACTED\] denied"):
        client.request("repos/o/r")


def test_client_request_wraps_transport_and_invalid_json(monkeypatch) -> None:
    client = bootstrap.GitHubClient("opaque")
    monkeypatch.setattr(
        bootstrap.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, "not-json", ""),
    )
    with pytest.raises(bootstrap.GitHubError, match="invalid JSON"):
        client.request("repos/o/r")
    monkeypatch.setattr(
        bootstrap.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("gh", 1)),
    )
    with pytest.raises(bootstrap.GitHubError, match="transport failed"):
        client.request("repos/o/r")


def test_invalid_default_sha_and_non_missing_branch_error_fail_closed() -> None:
    client = FakeClient()
    original = client.request

    def bad_sha(path: str, **kwargs: object) -> object:
        if path.endswith("/git/ref/heads/main"):
            return {"object": {"sha": "short"}}
        return original(path, **kwargs)

    client.request = bad_sha  # type: ignore[method-assign]
    with pytest.raises(bootstrap.GitHubError, match="invalid default-branch SHA"):
        bootstrap.bootstrap_repository(client, "demo")

    client = FakeClient()
    original = client.request

    def forbidden_branch(path: str, **kwargs: object) -> object:
        if path.endswith("/git/ref/heads/opencode/codeql-setup"):
            raise bootstrap.GitHubError("HTTP 403")
        return original(path, **kwargs)

    client.request = forbidden_branch  # type: ignore[method-assign]
    with pytest.raises(bootstrap.GitHubError, match="HTTP 403"):
        bootstrap.bootstrap_repository(client, "demo")


def test_load_payload_rejects_non_list(tmp_path) -> None:
    payload_path = tmp_path / "coverage.json"
    payload_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="root must be a list"):
        bootstrap.load_payload(payload_path, StringIO("[]"))


def test_main_bootstraps_each_gap(monkeypatch, tmp_path, capsys) -> None:
    payload_path = tmp_path / "coverage.json"
    payload_path.write_text(json.dumps(uncovered_payload()), encoding="utf-8")
    monkeypatch.setenv("OPENCODE_APP_TOKEN", "opaque")
    monkeypatch.setattr(bootstrap, "bootstrap_repository", lambda client, name: "created-pr-9")

    assert bootstrap.main([str(payload_path)]) == 0
    assert "repository=demo result=created-pr-9" in capsys.readouterr().out
