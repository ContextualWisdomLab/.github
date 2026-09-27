"""Trace required central producers through immutable native GitHub source objects."""

import json
from subprocess import CompletedProcess

import pytest

from tests.test_actions_queue_health import queue_health, pull_request, workflow_run


@pytest.mark.parametrize("current", [False, True])
@pytest.mark.parametrize("mutation", [None, "foreign_source", "file_path", "source_revision", "workflow_path", "suite_head", "run_id", "workflow_id", "suite_id", "event", "title", "shape", "commit_shape", "errors", "payload_type", "short", "null", "invalid_json", "failure", "timeout"])
def test_required_consumer_source_binds_native_suite_and_immutable_title(current, mutation, monkeypatch):
    """Refreshed PR associations cannot substitute for the native event commit."""
    repository = "ContextualWisdomLab/contextual-orchestrator"
    reviewed = "e655c530e659b1875a195fa78f96d0228ccf3b68"
    live = reviewed if current else "a" * 40
    run = workflow_run(36328534902, event="pull_request_target",
                       pull_requests=[{"number": 1268, "head": {"sha": live}}])
    run.update(node_id="WFR_kwLOTB3CTs8AAAAIdVlzdg", workflow_id=304003669,
               check_suite_id=98368770406, path=".github/workflows/strix.yml",
               workflow_url=f"https://api.github.com/repos/{repository}/actions/required_workflows/304003669",
               display_title=f"Strix Security Scan {repository}#1268@{reviewed}")
    node = {
        "databaseId": run["id"], "event": "pull_request_target",
        "displayTitle": run["display_title"],
        "workflow": {"databaseId": 304003669,
                     "resourcePath": f"/{repository}/actions/workflows/required/ContextualWisdomLab/.github/.github/workflows/strix.yml"},
        "file": {"path": run["path"], "repositoryName": "ContextualWisdomLab/.github",
                 "repositoryFileUrl": "https://github.com/ContextualWisdomLab/.github/blob/e07c7e1e6ddb7c2704ca1c51bdafb4b81b68e6b7/.github/workflows/strix.yml"},
        "checkSuite": {"databaseId": 98368770406, "commit": {"oid": reviewed}},
    }
    if mutation == "foreign_source":
        node["file"]["repositoryName"] = "owner/repo"
    elif mutation == "file_path":
        node["file"]["path"] += ".untrusted"
    elif mutation == "source_revision":
        node["file"]["repositoryFileUrl"] = node["file"]["repositoryFileUrl"].replace("e07c7e1e6ddb7c2704ca1c51bdafb4b81b68e6b7", "main")
    elif mutation == "workflow_path":
        node["workflow"]["resourcePath"] += ".untrusted"
    elif mutation == "suite_head":
        node["checkSuite"]["commit"]["oid"] = "b" * 40
    elif mutation == "run_id":
        node["databaseId"] += 1
    elif mutation == "workflow_id":
        node["workflow"]["databaseId"] += 1
    elif mutation == "suite_id":
        node["checkSuite"]["databaseId"] += 1
    elif mutation == "event":
        node["event"] = "pull_request"
    elif mutation == "title":
        node["displayTitle"] += "\n"
    elif mutation == "shape":
        node["checkSuite"] = "invalid"
    elif mutation == "commit_shape":
        node["checkSuite"]["commit"] = "invalid"

    def runner(command, **kwargs):
        """Return the captured native source shape without network or credentials."""
        assert command[:3] == ["gh", "api", "graphql"]
        assert kwargs["timeout"] == queue_health.GITHUB_API_TIMEOUT_SECONDS
        if mutation == "timeout":
            from subprocess import TimeoutExpired
            raise TimeoutExpired(command, 30)
        payload = {"data": {"nodes": [node]}}
        if mutation == "errors":
            payload["errors"] = [{"message": "unavailable"}]
        elif mutation == "short":
            payload["data"]["nodes"] = []
        elif mutation == "null":
            payload["data"]["nodes"] = [None]
        elif mutation == "payload_type":
            payload = []
        return CompletedProcess(command, int(mutation == "failure"),
                                "invalid" if mutation == "invalid_json" else json.dumps(payload), "")

    if mutation in {"run_id", "workflow_id", "suite_id", "event", "title", "shape", "commit_shape", "errors", "payload_type", "short", "null", "invalid_json", "failure", "timeout"}:
        with pytest.raises(queue_health.QueueHealthError):
            queue_health._bind_required_workflow_sources(repository, [run], runner=runner)
        return
    queue_health._bind_required_workflow_sources(repository, [run], runner=runner)
    normalized = queue_health._normalise_run(repository, run, [])
    normalized = queue_health._normalise_run(repository, normalized, [])
    pr = queue_health._normalise_pull_request(pull_request(1268, live))
    if mutation:
        assert queue_health._run_identity(normalized, {1268: pr}) == ("unlinked", None)
        assert "workflow_source" not in normalized
        assert normalized["display_title"] == ""
    else:
        assert queue_health._run_identity(normalized, {1268: pr}) == (
            "current_head" if current else "obsolete", 1268)
        assert normalized["workflow_source"]["repositoryName"] == "ContextualWisdomLab/.github"
        run.pop("workflow_source")
        run.update(status="completed", conclusion="cancelled")
        reads = []

        def github_json(endpoint, **kwargs):
            """Collect native terminal provenance before deciding to read jobs."""
            reads.append(endpoint)
            return {"default_branch": "main"} if endpoint == f"repos/{repository}" else []

        monkeypatch.setattr(queue_health, "github_json", github_json)
        monkeypatch.setattr(queue_health, "_read_pull_request_snapshot", lambda *a, **k: [pr])
        monkeypatch.setattr(queue_health, "_read_terminal_runs", lambda *a, **k: [])
        monkeypatch.setattr(queue_health, "_read_target_terminal_runs", lambda *a, **k: [run])
        snapshot = queue_health.collect_snapshot([repository], runner=runner)
        assert snapshot["collection_errors"] == []
        observed = snapshot["repositories"][0]["runs"]
        assert len(observed) == int(current)
        assert any("/jobs?" in endpoint for endpoint in reads) == current
        if current:
            report = queue_health.build_report(snapshot)
            assert report["runs"][0]["identity_state"] == "current_head"


def test_required_source_queries_keep_native_node_batches_bounded():
    """Cross the batch boundary without synthesizing source trust or extra reads."""
    repository = "ContextualWisdomLab/contextual-orchestrator"
    runs = [{"id": i, "node_id": f"WFR_{i}", "workflow_id": 9,
             "check_suite_id": i, "event": "pull_request_target", "display_title": "unknown",
             "workflow_url": f"https://api.github.com/repos/{repository}/actions/required_workflows/9"}
            for i in range(1, 102)]
    sizes = []

    def runner(command, **kwargs):
        """Return exactly the requested immutable native identities."""
        ids = json.loads(command[-1].split("{nodes(ids:", 1)[1].split("){", 1)[0])
        sizes.append(len(ids))
        nodes = [{"databaseId": int(node_id[4:]), "event": "pull_request_target",
                  "displayTitle": "unknown", "workflow": {"databaseId": 9}, "file": {},
                  "checkSuite": {"databaseId": int(node_id[4:]), "commit": {"oid": "a" * 40}}}
                 for node_id in ids]
        return CompletedProcess(command, 0, json.dumps({"data": {"nodes": nodes}}), "")

    queue_health._bind_required_workflow_sources(repository, runs, runner=runner)
    assert sizes == [100, 1]
    queue_health._bind_required_workflow_sources(repository, runs, runner=runner)
    assert sizes == [100, 1]
