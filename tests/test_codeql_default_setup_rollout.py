import base64
import builtins
import json
import runpy
import sys
from io import StringIO

import pytest

from scripts.ci import audit_codeql_default_setup_rollout as rollout

HEAD = "a" * 40


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.paths = []

    def request(self, path):
        self.paths.append(path)
        response = self.responses.get(path)
        if isinstance(response, Exception):
            raise response
        if response is None:
            raise AssertionError(f"unexpected request: {path}")
        return response


def encoded_workflow(source):
    raw = source.encode()
    return {
        "encoding": "base64",
        "size": len(raw),
        "content": base64.b64encode(raw).decode(),
    }


def live_responses(*, run_status="queued", uploader_source="name: CI\n"):
    repository = "ContextualWisdomLab/xtrmLLMBatchPython"
    return {
        f"/repos/{repository}/pulls/292": {"state": "open", "head": {"sha": HEAD}},
        f"/repos/{repository}/rulesets?includes_parents=true&per_page=100&page=1": [
            {"id": rollout.RULESET_ID}
        ],
        f"/repos/{repository}/rulesets/{rollout.RULESET_ID}?includes_parents=true": {
            "rules": [
                {
                    "type": "workflows",
                    "parameters": {
                        "workflows": [
                            {
                                "path": rollout.CENTRAL_CODEQL_PATH,
                                "ref": "refs/heads/main",
                                "repository_id": rollout.CENTRAL_REPOSITORY_ID,
                            }
                        ]
                    },
                }
            ]
        },
        f"/repos/{repository}/code-scanning/default-setup": {
            "state": "not-configured"
        },
        f"/repos/{repository}/actions/runs?head_sha={HEAD}&per_page=100&page=1": {
            "workflow_runs": [
                {
                    "path": rollout.CENTRAL_CODEQL_PATH,
                    "event": "pull_request",
                    "head_sha": HEAD,
                    "status": run_status,
                    "conclusion": None,
                }
            ]
        },
        f"/repos/{repository}/actions/workflows?per_page=100&page=1": {
            "workflows": [
                {
                    "path": ".github/workflows/ci.yml",
                    "state": "active",
                }
            ]
        },
        f"/repos/{repository}/contents/.github/workflows/ci.yml?ref={HEAD}": encoded_workflow(
            uploader_source
        ),
    }


def snapshot(**changes):
    value = {
        "name": "xtrmLLMBatchPython",
        "ruleset_applies": True,
        "central_codeql_required": True,
        "expected_head": HEAD,
        "central_codeql_head": HEAD,
        "central_codeql_status": "success",
        "default_setup_state": "not-configured",
        "active_advanced_upload": False,
    }
    value.update(changes)
    return value


def test_pilot_is_verified_only_after_exact_head_central_success():
    assert rollout.classify(snapshot()) == (
        "VERIFIED",
        "default setup is off and exact-head central CodeQL passed",
    )
    assert rollout.classify(snapshot(central_codeql_status="queued"))[0] == "WAIT"
    assert rollout.classify(snapshot(central_codeql_head="b" * 40))[0] == "BLOCK"


def test_default_setup_stays_on_until_central_success():
    assert (
        rollout.classify(
            snapshot(default_setup_state="configured", central_codeql_status="queued")
        )[0]
        == "WAIT"
    )
    assert rollout.classify(snapshot(default_setup_state="configured"))[0] == "READY_DISABLE"


def test_default_setup_and_advanced_uploader_conflict_fails_closed():
    result = rollout.classify(
        snapshot(default_setup_state="configured", active_advanced_upload=True)
    )
    assert result[0] == "BLOCK"
    assert "conflicts" in result[1]


def test_rollback_is_blocked_when_it_would_conflict_with_advanced_upload():
    result = rollout.classify(
        snapshot(central_codeql_status="failure", active_advanced_upload=True)
    )
    assert result[0] == "BLOCK"
    assert "cannot coexist" in result[1]


def test_ruleset_and_documented_exceptions_are_enforced():
    assert rollout.classify(snapshot(ruleset_applies=False))[0] == "BLOCK"
    for name in rollout.EXEMPT_REPOSITORIES:
        assert rollout.classify(snapshot(name=name, ruleset_applies=False))[0] == "EXEMPT"
        assert rollout.classify(snapshot(name=name, ruleset_applies=True))[0] == "BLOCK"


def test_cli_returns_nonzero_for_wait_and_zero_for_verified(capsys, monkeypatch):
    monkeypatch.setattr(rollout.sys, "stdin", StringIO(json.dumps([snapshot()])))
    assert rollout.main([]) == 0
    monkeypatch.setattr(
        rollout.sys,
        "stdin",
        StringIO(json.dumps([snapshot(central_codeql_status="queued")])),
    )
    assert rollout.main([]) == 1
    assert "state=WAIT" in capsys.readouterr().out


def test_live_snapshot_collects_exact_head_ruleset_run_and_uploader():
    source = (
        "steps:\n  - uses: github/codeql-action/analyze@" + "b" * 40 + "\n"
    )
    snapshot = rollout.collect_live_snapshot(
        FakeClient(live_responses(uploader_source=source)),
        "ContextualWisdomLab/xtrmLLMBatchPython",
        292,
    )
    assert snapshot == {
        "name": "xtrmLLMBatchPython",
        "ruleset_applies": True,
        "central_codeql_required": True,
        "expected_head": HEAD,
        "central_codeql_head": HEAD,
        "central_codeql_status": "queued",
        "default_setup_state": "not-configured",
        "active_advanced_upload": True,
    }


def test_live_snapshot_paginates_workflows_and_accepts_upload_never():
    responses = live_responses(
        uploader_source=(
            "steps:\n  - uses: github/codeql-action/analyze@" + "b" * 40
            + "\n    with:\n      upload: never\n"
        )
    )
    first_path = (
        "/repos/ContextualWisdomLab/xtrmLLMBatchPython/actions/workflows?"
        "per_page=100&page=1"
    )
    workflows = [
        {"path": f"dynamic/filler/{index}", "state": "active"}
        for index in range(99)
    ] + responses[first_path]["workflows"]
    responses[first_path] = {"workflows": workflows}
    responses[first_path[:-1] + "2"] = {"workflows": []}
    client = FakeClient(responses)
    result = rollout.collect_live_snapshot(
        client, "ContextualWisdomLab/xtrmLLMBatchPython", 292
    )
    assert result["active_advanced_upload"] is False
    assert first_path[:-1] + "2" in client.paths


def test_live_snapshot_rejects_ambiguous_exact_head_central_runs():
    responses = live_responses()
    path = f"/repos/ContextualWisdomLab/xtrmLLMBatchPython/actions/runs?head_sha={HEAD}&per_page=100&page=1"
    responses[path]["workflow_runs"] *= 2
    try:
        rollout.collect_live_snapshot(
            FakeClient(responses), "ContextualWisdomLab/xtrmLLMBatchPython", 292
        )
    except rollout.EvidenceError as exc:
        assert "missing or ambiguous" in str(exc)
    else:
        raise AssertionError("ambiguous runs must fail closed")


def test_live_snapshot_rejects_missing_ruleset_and_workflow_source_evidence():
    responses = live_responses()
    ruleset_path = "/repos/ContextualWisdomLab/xtrmLLMBatchPython/rulesets?includes_parents=true&per_page=100&page=1"
    responses[ruleset_path] = []
    result = rollout.collect_live_snapshot(
        FakeClient(responses), "ContextualWisdomLab/xtrmLLMBatchPython", 292
    )
    assert rollout.classify(result)[0] == "BLOCK"

    responses = live_responses()
    source_path = f"/repos/ContextualWisdomLab/xtrmLLMBatchPython/contents/.github/workflows/ci.yml?ref={HEAD}"
    responses[source_path] = {"encoding": "none", "size": 1, "content": "x"}
    try:
        rollout.collect_live_snapshot(
            FakeClient(responses), "ContextualWisdomLab/xtrmLLMBatchPython", 292
        )
    except rollout.EvidenceError as exc:
        assert "unavailable" in str(exc)
    else:
        raise AssertionError("missing source evidence must fail closed")


def test_live_snapshot_ignores_registered_workflow_deleted_at_exact_head():
    responses = live_responses()
    source_path = f"/repos/ContextualWisdomLab/xtrmLLMBatchPython/contents/.github/workflows/ci.yml?ref={HEAD}"
    responses[source_path] = rollout.GitHubError("gh: Not Found (HTTP 404)")
    result = rollout.collect_live_snapshot(
        FakeClient(responses), "ContextualWisdomLab/xtrmLLMBatchPython", 292
    )
    assert result["active_advanced_upload"] is False


def test_live_snapshot_rejects_head_movement_during_collection():
    class MovingHeadClient(FakeClient):
        reads = 0

        def request(self, path):
            if path.endswith("/pulls/292"):
                self.reads += 1
                if self.reads == 2:
                    return {"state": "open", "head": {"sha": "b" * 40}}
            return super().request(path)

    try:
        rollout.collect_live_snapshot(
            MovingHeadClient(live_responses()),
            "ContextualWisdomLab/xtrmLLMBatchPython",
            292,
        )
    except rollout.EvidenceError as exc:
        assert "head changed" in str(exc)
    else:
        raise AssertionError("moving exact-head evidence must fail closed")


def test_pagination_rejects_malformed_and_unbounded_evidence():
    with pytest.raises(rollout.EvidenceError, match="malformed pagination"):
        rollout._pages(FakeClient({"/items?per_page=100&page=1": {}}), "/items")

    pages = {
        f"/items?per_page=100&page={page}": [{}] * 100
        for page in range(1, rollout.MAX_PAGES + 1)
    }
    with pytest.raises(rollout.EvidenceError, match="pagination exceeded"):
        rollout._pages(FakeClient(pages), "/items")


@pytest.mark.parametrize(
    ("source", "active"),
    (
        (
            "steps:\n  - name: disabled\n    if: ${{ false }}\n"
            "    uses: github/codeql-action/analyze@pin\n",
            False,
        ),
        (
            "steps:\n  - name: disabled\n    uses: github/codeql-action/analyze@pin\n"
            "    with:\n      upload: 'never'\n  - name: next\n    run: true\n",
            False,
        ),
        (
            "steps:\n  - name: active\n    uses: github/codeql-action/upload-sarif@pin\n",
            True,
        ),
    ),
)
def test_advanced_uploader_detection_honors_only_local_disabling(source, active):
    assert rollout._has_active_advanced_upload(source) is active


def test_live_snapshot_rejects_ambiguous_or_invalid_workflow_sources():
    repository = "ContextualWisdomLab/xtrmLLMBatchPython"
    workflow_path = f"/repos/{repository}/actions/workflows?per_page=100&page=1"
    source_path = f"/repos/{repository}/contents/.github/workflows/ci.yml?ref={HEAD}"

    cases = []
    duplicate = live_responses()
    duplicate[workflow_path]["workflows"] *= 2
    cases.append((duplicate, "identity is ambiguous"))

    lookup_failure = live_responses()
    lookup_failure[source_path] = rollout.GitHubError("HTTP 500")
    cases.append((lookup_failure, "source lookup failed"))

    invalid_size = live_responses()
    invalid_size[source_path]["size"] = -1
    cases.append((invalid_size, "invalid size"))

    invalid_base64 = live_responses()
    invalid_base64[source_path]["content"] = "!"
    cases.append((invalid_base64, "source is invalid"))

    size_mismatch = live_responses()
    size_mismatch[source_path]["size"] += 1
    cases.append((size_mismatch, "size mismatch"))

    for responses, message in cases:
        with pytest.raises(rollout.EvidenceError, match=message):
            rollout.collect_live_snapshot(FakeClient(responses), repository, 292)


@pytest.mark.parametrize(
    ("repository", "pr_number", "message"),
    (
        ("Other/example", 1, "must belong"),
        ("ContextualWisdomLab/example", 0, "must be positive"),
    ),
)
def test_live_snapshot_rejects_invalid_identity(repository, pr_number, message):
    with pytest.raises(rollout.EvidenceError, match=message):
        rollout.collect_live_snapshot(FakeClient({}), repository, pr_number)


def test_live_snapshot_rejects_ambiguous_ruleset_owner_and_missing_states():
    repository = "ContextualWisdomLab/xtrmLLMBatchPython"
    pull_path = f"/repos/{repository}/pulls/292"
    rulesets_path = f"/repos/{repository}/rulesets?includes_parents=true&per_page=100&page=1"
    detail_path = f"/repos/{repository}/rulesets/{rollout.RULESET_ID}?includes_parents=true"
    setup_path = f"/repos/{repository}/code-scanning/default-setup"
    runs_path = f"/repos/{repository}/actions/runs?head_sha={HEAD}&per_page=100&page=1"

    closed = live_responses()
    closed[pull_path] = {"state": "closed", "head": {"sha": HEAD}}
    ambiguous_ruleset = live_responses()
    ambiguous_ruleset[rulesets_path] *= 2
    ambiguous_owner = live_responses()
    ambiguous_owner[detail_path]["rules"][0]["parameters"]["workflows"] *= 2
    missing_setup = live_responses()
    missing_setup[setup_path] = {"state": "new-state"}
    missing_status = live_responses()
    missing_status[runs_path]["workflow_runs"][0].update(status=None, conclusion=None)

    for responses, message in (
        (closed, "not open"),
        (ambiguous_ruleset, "ruleset evidence is ambiguous"),
        (ambiguous_owner, "ruleset owner is ambiguous"),
        (missing_setup, "default-setup state is unavailable"),
        (missing_status, "has no status"),
    ):
        with pytest.raises(rollout.EvidenceError, match=message):
            rollout.collect_live_snapshot(FakeClient(responses), repository, 292)


def test_exempt_snapshot_revalidates_head_and_classification_edges():
    repository = "ContextualWisdomLab/noema"
    pull_path = f"/repos/{repository}/pulls/7"
    rulesets_path = f"/repos/{repository}/rulesets?includes_parents=true&per_page=100&page=1"
    client = FakeClient(
        {
            pull_path: {"state": "open", "head": {"sha": HEAD}},
            rulesets_path: [],
        }
    )
    assert rollout.collect_live_snapshot(client, repository, 7) == {
        "name": "noema",
        "ruleset_applies": False,
    }
    assert rollout.classify(snapshot(default_setup_state="unsupported"))[0] == "BLOCK"
    assert rollout.classify(snapshot(central_codeql_status="failure"))[0] == "ROLLBACK"

    class MovingExemptClient(FakeClient):
        reads = 0

        def request(self, path):
            if path == pull_path:
                self.reads += 1
                if self.reads == 2:
                    return {"state": "open", "head": {"sha": "b" * 40}}
            return super().request(path)

    with pytest.raises(rollout.EvidenceError, match="head changed"):
        rollout.collect_live_snapshot(
            MovingExemptClient(client.responses), repository, 7
        )


def test_payload_file_and_cli_error_paths(tmp_path, monkeypatch, capsys):
    payload_path = tmp_path / "snapshots.json"
    payload_path.write_text(json.dumps([snapshot()]), encoding="utf-8")
    assert rollout.load_payload(payload_path, StringIO()) == [snapshot()]
    with pytest.raises(ValueError, match="array of objects"):
        rollout.load_payload(None, StringIO("{}"))

    assert rollout.main([str(payload_path), "--repository", "ContextualWisdomLab/x", "--pr", "1"]) == 2
    monkeypatch.setattr(rollout.sys, "stdin", StringIO("{"))
    assert rollout.main([]) == 2
    assert "unable to load CodeQL rollout snapshots" in capsys.readouterr().err


def test_live_cli_collects_one_snapshot(monkeypatch, capsys):
    fake_client = object()
    monkeypatch.setattr(
        rollout.GitHubClient,
        "from_environment",
        classmethod(lambda cls: fake_client),
    )
    monkeypatch.setattr(
        rollout,
        "collect_live_snapshot",
        lambda client, repository, pr: snapshot(),
    )
    assert rollout.main(
        ["--repository", "ContextualWisdomLab/example", "--pr", "7"]
    ) == 0
    assert "state=VERIFIED" in capsys.readouterr().out


def test_direct_script_import_falls_back_to_sibling_module(monkeypatch):
    script_path = rollout.Path(rollout.__file__)
    real_import = builtins.__import__

    def import_with_package_missing(name, *args, **kwargs):
        if name == "scripts.ci.organization_commercial_readiness_loop":
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_with_package_missing)
    monkeypatch.setattr(sys, "path", [str(script_path.parent), *sys.path])
    namespace = runpy.run_path(str(script_path), run_name="rollout_direct_import_test")
    assert namespace["GitHubClient"] is not None
