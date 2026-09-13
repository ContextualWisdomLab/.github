"""Request owners close failed responses without masking failure or cancellation."""

from contextlib import nullcontext
from io import BytesIO
from itertools import count
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from scripts.ci import noema_review_gate as noema
from scripts.ci import pingora_edge_policy as policy
from scripts.ci import reconcile_repository_metadata as metadata
from scripts.ci import sandboxed_web_e2e as sandbox


@pytest.mark.parametrize("caller_name", ["policy", "pages", "readiness", "noema"])
@pytest.mark.parametrize("close_error_type", [None, OSError, ValueError, RuntimeError, KeyboardInterrupt, SystemExit])
def test_http_error_owner_preserves_failure_and_cancellation(monkeypatch, caller_name, close_error_type):
    """Removing cleanup or letting its exception replace the result breaks this contract."""
    response_body = BytesIO(b"fixture response")

    class ResponseError(HTTPError):
        def close(self):
            super().close()
            if close_error_type is not None:
                raise close_error_type("fixture cleanup")

    response_error = ResponseError("https://example.test", 502, "fixture failure", {}, response_body)

    def fail_request(*_args, **_kwargs):
        raise response_error

    def opener_factory(*_args):
        return SimpleNamespace(open=fail_request)

    expected_error, expected_message = {
        "policy": (policy.PolicyError, "GitHub API request failed"),
        "pages": (RuntimeError, "not reachable"),
        "readiness": (None, ""),
        "noema": (noema.NoemaTransportError, "Noema gateway transport failed"),
    }[caller_name]
    if close_error_type in (KeyboardInterrupt, SystemExit):
        expected_error, expected_message = close_error_type, "fixture cleanup"
    expected_outcome = pytest.raises(expected_error, match=expected_message) if expected_error else nullcontext()

    try:
        with expected_outcome:
            if caller_name == "policy":
                monkeypatch.setattr(policy.github_opener, "open", fail_request)
                policy._github_open_json("https://api.github.com/repos/fixture/example", "fixture-token")
            elif caller_name == "pages":
                monkeypatch.setattr(metadata, "build_opener", opener_factory)
                metadata._pages_publication_ready("Fixture", {
                    "status": "built", "html_url": "https://contextualwisdomlab.github.io/Fixture/",
                })
            elif caller_name == "noema":
                monkeypatch.setenv("NOEMA_LLM_API_URL", "https://8.8.8.8/chat")
                monkeypatch.setenv("NOEMA_LLM_API_KEY", "fixture-token")
                monkeypatch.setenv("NOEMA_LLM_MODEL", "orchestrator/free")
                monkeypatch.setattr(noema.urllib.request, "build_opener", opener_factory)
                noema.call_llm("fixture/example", 1, {"headRefOid": "a" * 40}, "", False, "a" * 40)
            else:
                monkeypatch.setattr(sandbox.urllib.request, "build_opener", opener_factory)
                monkeypatch.setattr(sandbox, "time", SimpleNamespace(
                    monotonic=count().__next__, sleep=lambda _seconds: None,
                ))
                service_state = SimpleNamespace(process=SimpleNamespace(poll=lambda: None))
                assert sandbox.wait_for_url("http://127.0.0.1:8123/ready", 2, service_state) is False
        assert response_error.closed
        assert response_body.closed
    finally:
        HTTPError.close(response_error)
