"""Permanent consumer regressions for truncated Noema formal approvals."""

from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import socket

import pytest

from scripts.ci import noema_review_gate as gate


DIFF = """diff --git a/src/runtime.py b/src/runtime.py
--- a/src/runtime.py
+++ b/src/runtime.py
@@ -1,2 +1,2 @@
-old = 1
+new = 1
-old_again = 2
+new_again = 2
"""
PR = {"title": "fixture", "headRefOid": "a" * 40}


def _approve_verdict() -> dict:
    return {
        "decision": "approve",
        "summary": "The changed lines are bounded.",
        "findings": [],
        "reviewed_lines": [
            {"path": "src/runtime.py", "line": 1, "side": "RIGHT", "analysis": "Checked."}
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "No unresolved risk in the reviewed diff.",
            "probes": [
                {
                    "path": "src/runtime.py",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "The first replacement changes the runtime contract.",
                    "attack_or_counterexample": "Compare the exact first replacement.",
                    "evidence": "The replacement preserves the bounded fixture contract.",
                    "outcome": "falsified",
                },
                {
                    "path": "src/runtime.py",
                    "line": 2,
                    "side": "RIGHT",
                    "hypothesis": "The second replacement changes the runtime contract.",
                    "attack_or_counterexample": "Compare the exact second replacement.",
                    "evidence": "The replacement preserves the bounded fixture contract.",
                    "outcome": "falsified",
                },
            ],
        },
    }


def _request_changes_verdict() -> dict:
    verdict = _approve_verdict()
    verdict["decision"] = "request_changes"
    verdict["summary"] = "A concrete changed-line issue remains."
    verdict["findings"] = [
        {
            "severity": "high",
            "file": "src/runtime.py",
            "line": 1,
            "side": "RIGHT",
            "message": "The first replacement is unsafe.",
        }
    ]
    verdict["adversarial_validation"]["status"] = "failed"
    verdict["adversarial_validation"]["probes"][0]["outcome"] = "confirmed"
    return verdict


class _Response:
    def __init__(self, verdict: dict) -> None:
        self.verdict = verdict

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(
            {"model": "synthetic/offline", "choices": [{"message": {"content": json.dumps(self.verdict)}}]}
        ).encode("utf-8")


def _call(monkeypatch: pytest.MonkeyPatch, verdict: dict, *, truncated: bool) -> dict:
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example.test/chat")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "synthetic")
    monkeypatch.setenv("NOEMA_LLM_MODEL", "synthetic/offline")
    monkeypatch.setattr(gate.socket, "getaddrinfo", lambda *_args, **_kwargs: (_ for _ in ()).throw(socket.gaierror()))

    class _Opener:
        def open(self, _request: object) -> _Response:
            return _Response(verdict)

    monkeypatch.setattr(gate.urllib.request, "build_opener", lambda *_args: _Opener())
    return gate.call_llm(
        "owner/repo",
        7,
        PR,
        DIFF,
        truncated,
        PR["headRefOid"],
        "synthetic context",
        ("src/runtime.py",),
    )


def test_complete_diff_approve_remains_admitted(monkeypatch: pytest.MonkeyPatch) -> None:
    verdict = _call(monkeypatch, _approve_verdict(), truncated=False)
    assert verdict["decision"] == "approve"


def test_truncated_approve_is_model_output_failure_not_capacity(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(gate.NoemaModelOutputError, match="complete diff") as exc_info:
        _call(monkeypatch, _approve_verdict(), truncated=True)
    assert not isinstance(exc_info.value, gate.NoemaTransportError)
    assert "provider_capacity_unavailable" not in capsys.readouterr().out


def test_truncated_partial_comment_remains_admitted(monkeypatch: pytest.MonkeyPatch) -> None:
    verdict = _approve_verdict()
    verdict["decision"] = "comment"
    verdict["summary"] = "Partial context is recorded without formal approval."
    verdict["reviewed_lines"] = []
    verdict["adversarial_validation"] = {}
    assert _call(monkeypatch, verdict, truncated=True)["decision"] == "comment"


def test_truncated_request_changes_with_confirmed_evidence_remains_admitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _call(monkeypatch, _request_changes_verdict(), truncated=True)["decision"] == "request_changes"


@pytest.mark.parametrize("decision", ["approve", "APPROVE", " approve "])
def test_truncated_approval_rejection_uses_normalized_decision(
    monkeypatch: pytest.MonkeyPatch, decision: str,
) -> None:
    verdict = _approve_verdict()
    verdict["decision"] = decision
    with pytest.raises(gate.NoemaModelOutputError, match="complete diff"):
        _call(monkeypatch, verdict, truncated=True)


def test_truncated_request_changes_without_confirmed_finding_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verdict = _request_changes_verdict()
    verdict["adversarial_validation"]["probes"][0]["outcome"] = "falsified"
    with pytest.raises(gate.NoemaModelOutputError, match="confirmed probe on a published finding"):
        _call(monkeypatch, verdict, truncated=True)


def test_truncated_malformed_comment_is_still_model_output_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verdict = _approve_verdict()
    verdict["decision"] = "comment"
    verdict["findings"] = "not a list"
    with pytest.raises(gate.NoemaModelOutputError, match="findings must be a list of objects"):
        _call(monkeypatch, verdict, truncated=True)


def _prepare_fixture(monkeypatch: pytest.MonkeyPatch, verdict: dict, *, truncated: bool):
    """Replace only unavailable HTTP/command boundaries; keep real consumers."""
    module_path = Path(__file__).resolve().parents[1] / ".github/actions/noema-review/two_phase.py"
    spec = importlib.util.spec_from_file_location("noema_truncation_two_phase", module_path)
    assert spec is not None and spec.loader is not None
    phase = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(phase)
    pr = {**PR, "number": 7, "body": "", "state": "OPEN", "isDraft": False,
          "baseRefOid": "b" * 40, "author": {"login": "fixture-author"},
          "reviews": {"nodes": []}, "reviewThreads": {"nodes": []}}
    padding = "diff --git a/docs/padding.md b/docs/padding.md\n--- /dev/null\n+++ b/docs/padding.md\n@@ -0,0 +1,70 @@\n"
    full = DIFF + padding + ("+" + "p" * 1000 + "\n") * (70 if truncated else 1)
    full += "diff --git a/src/omitted.py b/src/omitted.py\n--- /dev/null\n+++ b/src/omitted.py\n@@ -0,0 +1 @@\n+enabled = False\n"
    posts, requests = [], []

    def recording_run(argv, *, stdin=None):
        if argv[:3] == ["gh", "api", "graphql"]:
            return json.dumps({"data": {"repository": {"pullRequest": pr}}})
        if "-X" in argv:
            assert argv == ["gh", "api", "-X", "POST", "repos/owner/repo/pulls/7/reviews", "--input", "-"]
            posts.append(json.loads(stdin))
            return "{}"
        if argv[2] == "repos/owner/repo/pulls/7":
            return full
        if argv[2] == "repos/owner/repo/pulls/7/files":
            return "\n".join(json.dumps([path, "added"]) for path in ("src/runtime.py", "docs/padding.md", "src/omitted.py"))
        if argv[2].startswith("repos/owner/repo/contents/"):
            raise RuntimeError("Synthetic unavailable content HTTP boundary")
        raise AssertionError("Unexpected synthetic command")

    def open_response(_opener, request):
        requests.append(json.loads(request.data))
        return _Response(verdict)

    for name in tuple(os.environ):
        if name.startswith(("NOEMA_", "GITHUB_", "GH_")):
            monkeypatch.delenv(name, raising=False)
    for name, value in {
        "NOEMA_REVIEW_ACTOR": "fixture-review[bot]", "NOEMA_REVIEW_INSTALLATION_ID": "123",
        "NOEMA_REVIEW_TOKEN_SOURCE": phase.CANONICAL_APP_TOKEN_SOURCE,
        "NOEMA_LLM_API_URL": "http://127.0.0.1:9/v1/chat/completions",
        "CONTEXTUAL_ORCHESTRATOR_BASE_URL": "http://127.0.0.1:9",
        "NOEMA_LLM_API_KEY": "synthetic", "NOEMA_LLM_MODEL": "synthetic/offline",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(gate, "run", recording_run)
    monkeypatch.setattr(gate.urllib.request.OpenerDirector, "open", open_response)
    return phase, posts, requests


def test_real_prepare_rejects_truncated_approve_without_envelope_or_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    phase, posts, requests = _prepare_fixture(monkeypatch, _approve_verdict(), truncated=True)
    envelope = tmp_path / "envelope.json"
    output = tmp_path / "github_output"
    output.write_text("OUTPUT_SENTINEL\n")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    bounded, truncated = gate.fetch_diff("owner/repo", 7)
    assert truncated is True
    assert "src/omitted.py" not in bounded
    with pytest.raises(gate.NoemaModelOutputError, match="complete diff"):
        phase.prepare_verdict("owner/repo", 7, PR["headRefOid"], envelope)
    assert len(requests) == 1
    assert not envelope.exists()
    assert output.read_text() == "OUTPUT_SENTINEL\n"
    assert posts == []
    assert "provider_capacity_unavailable" not in capsys.readouterr().out
    with pytest.raises(RuntimeError, match="unavailable for publication"):
        phase.publish_verdict("owner/repo", 7, PR["headRefOid"], envelope)
    assert posts == []


@pytest.mark.parametrize("decision,truncated,event", [
    ("approve", False, "APPROVE"), ("comment", True, "COMMENT"),
    ("request_changes", True, "REQUEST_CHANGES"),
])
def test_real_prepare_publish_preserves_supported_decisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, decision: str, truncated: bool, event: str,
) -> None:
    verdict = _request_changes_verdict() if decision == "request_changes" else _approve_verdict()
    verdict["decision"] = decision
    phase, posts, requests = _prepare_fixture(monkeypatch, verdict, truncated=truncated)
    envelope = tmp_path / "envelope.json"
    assert phase.prepare_verdict("owner/repo", 7, PR["headRefOid"], envelope) == 0
    assert phase._read_envelope(envelope)["verdict"] == verdict
    assert len(requests) == 1
    assert posts == []
    monkeypatch.setenv("NOEMA_REVIEW_TOKEN_SOURCE", phase.REFRESHED_APP_TOKEN_SOURCE)
    assert phase.publish_verdict("owner/repo", 7, PR["headRefOid"], envelope) == 0
    assert [post["event"] for post in posts] == [event]
    assert posts[0]["commit_id"] == PR["headRefOid"]
    assert not envelope.exists()


@pytest.mark.parametrize("status,capacity", [(400, False), (503, True)])
def test_truncated_http_error_keeps_transport_classification(
    monkeypatch: pytest.MonkeyPatch, status: int, capacity: bool,
) -> None:
    phase, posts, requests = _prepare_fixture(monkeypatch, _approve_verdict(), truncated=True)
    calls = []

    def http_error(_opener, request):
        calls.append(request)
        raise gate.urllib.error.HTTPError(request.full_url, status, "Synthetic unavailable", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(gate.urllib.request.OpenerDirector, "open", http_error)
    with pytest.raises(gate.NoemaTransportError) as exc_info:
        gate.call_llm("owner/repo", 7, PR, DIFF, True, PR["headRefOid"])
    assert not isinstance(exc_info.value, gate.NoemaModelOutputError)
    assert exc_info.value.http_status == status
    assert exc_info.value.capacity_unavailable is capacity
    assert len(calls) == 1
    assert posts == []
