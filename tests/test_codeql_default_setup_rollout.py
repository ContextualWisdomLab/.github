import base64
import json
from io import StringIO
from pathlib import Path

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


def test_pages_rejects_malformed_batches_and_exhausted_pagination():
    class ListClient:
        def __init__(self, pages):
            self.pages = pages
            self.calls = 0

        def request(self, _path):
            page = self.pages[self.calls]
            self.calls += 1
            return page

    with pytest.raises(rollout.EvidenceError, match="malformed pagination"):
        rollout._pages(ListClient([{"not": "a-list"}]), "/repos/x/rulesets")

    full_pages = [[{"id": i} for i in range(100)] for _ in range(rollout.MAX_PAGES)]
    with pytest.raises(rollout.EvidenceError, match="exceeded"):
        rollout._pages(ListClient(full_pages), "/repos/x/rulesets")


def test_step_disabled_upload_scans_across_multi_line_step_boundaries():
    source = "\n".join(
        [
            "steps:",
            "  - name: Checkout",
            "    run: echo hi",
            "  - name: Analyze",
            "    uses: github/codeql-action/analyze@" + "b" * 40,
            "    with:",
            "      upload: never",
            "  - name: Another step",
            "    run: echo done",
        ]
    )
    assert rollout._has_active_advanced_upload(source) is False

    active_source = "\n".join(
        [
            "steps:",
            "  - name: Checkout",
            "    run: echo hi",
            "  - name: Analyze",
            "    uses: github/codeql-action/analyze@" + "b" * 40,
            "  - name: Another step",
            "    run: echo done",
        ]
    )
    assert rollout._has_active_advanced_upload(active_source) is True


def test_active_advanced_uploader_rejects_ambiguous_and_failed_source_lookups():
    repository = "ContextualWisdomLab/xtrmLLMBatchPython"
    duplicate_path_client = FakeClient(
        {
            f"/repos/{repository}/actions/workflows?per_page=100&page=1": {
                "workflows": [
                    {"path": ".github/workflows/ci.yml", "state": "active"},
                    {"path": ".github/workflows/ci.yml", "state": "active"},
                ]
            },
            f"/repos/{repository}/contents/.github/workflows/ci.yml?ref={HEAD}": encoded_workflow(
                "name: CI\n"
            ),
        }
    )
    with pytest.raises(rollout.EvidenceError, match="ambiguous"):
        rollout._active_advanced_uploader(duplicate_path_client, repository, HEAD)

    lookup_failure_client = FakeClient(
        {
            f"/repos/{repository}/actions/workflows?per_page=100&page=1": {
                "workflows": [{"path": ".github/workflows/ci.yml", "state": "active"}]
            },
            f"/repos/{repository}/contents/.github/workflows/ci.yml?ref={HEAD}": rollout.GitHubError(
                "gh: rate limited (HTTP 429)"
            ),
        }
    )
    with pytest.raises(rollout.EvidenceError, match="source lookup failed"):
        rollout._active_advanced_uploader(lookup_failure_client, repository, HEAD)


def test_active_advanced_uploader_rejects_invalid_encoded_source():
    repository = "ContextualWisdomLab/xtrmLLMBatchPython"
    path = f"/repos/{repository}/contents/.github/workflows/ci.yml?ref={HEAD}"
    workflows_path = f"/repos/{repository}/actions/workflows?per_page=100&page=1"
    workflows = {
        "workflows": [{"path": ".github/workflows/ci.yml", "state": "active"}]
    }

    oversized_client = FakeClient(
        {
            workflows_path: workflows,
            path: {"encoding": "base64", "size": rollout.MAX_WORKFLOW_BYTES + 1, "content": ""},
        }
    )
    with pytest.raises(rollout.EvidenceError, match="invalid size"):
        rollout._active_advanced_uploader(oversized_client, repository, HEAD)

    bad_base64_client = FakeClient(
        {
            workflows_path: workflows,
            path: {"encoding": "base64", "size": 3, "content": "not-valid-base64!!"},
        }
    )
    with pytest.raises(rollout.EvidenceError, match="is invalid"):
        rollout._active_advanced_uploader(bad_base64_client, repository, HEAD)

    mismatched_size_client = FakeClient(
        {
            workflows_path: workflows,
            path: {
                "encoding": "base64",
                "size": 999,
                "content": base64.b64encode(b"short").decode(),
            },
        }
    )
    with pytest.raises(rollout.EvidenceError, match="size mismatch"):
        rollout._active_advanced_uploader(mismatched_size_client, repository, HEAD)


def test_collect_live_snapshot_rejects_invalid_repository_and_pr_number():
    with pytest.raises(rollout.EvidenceError, match="ContextualWisdomLab"):
        rollout.collect_live_snapshot(FakeClient({}), "someone-else/repo", 1)
    with pytest.raises(rollout.EvidenceError, match="must be positive"):
        rollout.collect_live_snapshot(
            FakeClient({}), "ContextualWisdomLab/example", 0
        )


def test_collect_live_snapshot_rejects_a_closed_or_headless_pull_request():
    repository = "ContextualWisdomLab/example"
    with pytest.raises(rollout.EvidenceError, match="not open"):
        rollout.collect_live_snapshot(
            FakeClient({f"/repos/{repository}/pulls/1": {"state": "closed", "head": {"sha": HEAD}}}),
            repository,
            1,
        )


def test_collect_live_snapshot_rejects_ambiguous_ruleset_and_owner_evidence():
    repository = "ContextualWisdomLab/xtrmLLMBatchPython"
    responses = live_responses()
    ruleset_path = f"/repos/{repository}/rulesets?includes_parents=true&per_page=100&page=1"
    responses[ruleset_path] = [{"id": rollout.RULESET_ID}, {"id": rollout.RULESET_ID}]
    with pytest.raises(rollout.EvidenceError, match="ruleset evidence is ambiguous"):
        rollout.collect_live_snapshot(FakeClient(responses), repository, 292)

    responses = live_responses()
    detail_path = f"/repos/{repository}/rulesets/{rollout.RULESET_ID}?includes_parents=true"
    owner = {
        "path": rollout.CENTRAL_CODEQL_PATH,
        "ref": "refs/heads/main",
        "repository_id": rollout.CENTRAL_REPOSITORY_ID,
    }
    responses[detail_path] = {"rules": [{"type": "workflows", "parameters": {"workflows": [owner, owner]}}]}
    with pytest.raises(rollout.EvidenceError, match="owner is ambiguous"):
        rollout.collect_live_snapshot(FakeClient(responses), repository, 292)


def test_collect_live_snapshot_handles_exempt_repositories():
    exempt_name = next(iter(rollout.EXEMPT_REPOSITORIES))
    repository = f"ContextualWisdomLab/{exempt_name}"
    responses = {
        f"/repos/{repository}/pulls/1": {"state": "open", "head": {"sha": HEAD}},
        f"/repos/{repository}/rulesets?includes_parents=true&per_page=100&page=1": [],
    }
    result = rollout.collect_live_snapshot(FakeClient(responses), repository, 1)
    assert result == {"name": exempt_name, "ruleset_applies": False}


def test_collect_live_snapshot_rejects_head_movement_for_an_exempt_repository():
    exempt_name = next(iter(rollout.EXEMPT_REPOSITORIES))
    repository = f"ContextualWisdomLab/{exempt_name}"

    class MovingHeadClient(FakeClient):
        reads = 0

        def request(self, path):
            if path.endswith("/pulls/1"):
                self.reads += 1
                if self.reads == 2:
                    return {"state": "open", "head": {"sha": "b" * 40}}
            return super().request(path)

    responses = {
        f"/repos/{repository}/pulls/1": {"state": "open", "head": {"sha": HEAD}},
        f"/repos/{repository}/rulesets?includes_parents=true&per_page=100&page=1": [],
    }
    with pytest.raises(rollout.EvidenceError, match="head changed"):
        rollout.collect_live_snapshot(MovingHeadClient(responses), repository, 1)


def test_collect_live_snapshot_rejects_unusable_default_setup_state():
    responses = live_responses()
    repository = "ContextualWisdomLab/xtrmLLMBatchPython"
    responses[f"/repos/{repository}/code-scanning/default-setup"] = {"state": "unknown"}
    with pytest.raises(rollout.EvidenceError, match="default-setup state is unavailable"):
        rollout.collect_live_snapshot(FakeClient(responses), repository, 292)


def test_collect_live_snapshot_rejects_a_central_run_with_no_status():
    responses = live_responses()
    repository = "ContextualWisdomLab/xtrmLLMBatchPython"
    path = f"/repos/{repository}/actions/runs?head_sha={HEAD}&per_page=100&page=1"
    responses[path]["workflow_runs"][0]["status"] = ""
    responses[path]["workflow_runs"][0]["conclusion"] = None
    with pytest.raises(rollout.EvidenceError, match="has no status"):
        rollout.collect_live_snapshot(FakeClient(responses), repository, 292)


def test_classify_fails_closed_on_unsupported_default_setup_state():
    result = rollout.classify(snapshot(default_setup_state="mid-migration"))
    assert result == ("BLOCK", "default-setup state is unavailable or unsupported")


def test_classify_rolls_back_when_central_codeql_fails_with_no_active_uploader():
    result = rollout.classify(snapshot(central_codeql_status="failure"))
    assert result[0] == "ROLLBACK"


def test_load_payload_reads_a_file_and_rejects_the_wrong_shape(tmp_path: Path):
    path = tmp_path / "snapshots.json"
    path.write_text(json.dumps([snapshot()]), encoding="utf-8")
    assert rollout.load_payload(path, StringIO("")) == [snapshot()]

    with pytest.raises(ValueError, match="array of objects"):
        rollout.load_payload(None, StringIO(json.dumps({"not": "a-list"})))
    with pytest.raises(ValueError, match="array of objects"):
        rollout.load_payload(None, StringIO(json.dumps(["not-a-dict"])))


def test_cli_rejects_conflicting_live_mode_arguments_and_prints_errors(capsys):
    assert rollout.main(["--repository", "ContextualWisdomLab/example"]) == 2
    assert "requires --repository and --pr" in capsys.readouterr().err

    assert rollout.main(["snapshots.json", "--repository", "ContextualWisdomLab/example", "--pr", "1"]) == 2
    assert "requires --repository and --pr" in capsys.readouterr().err


def test_cli_reports_live_collection_failures(capsys, monkeypatch):
    def failing_client():
        raise rollout.GitHubError("gh: unauthorized")

    monkeypatch.setattr(rollout.GitHubClient, "from_environment", staticmethod(failing_client))
    assert rollout.main(["--repository", "ContextualWisdomLab/example", "--pr", "1"]) == 2
    assert "unable to load CodeQL rollout snapshots" in capsys.readouterr().err
