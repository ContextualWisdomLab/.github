from __future__ import annotations

import ast
from pathlib import Path
import subprocess

BASE_SHA = "960b08456de4c87a5a833938220d6d83f68d61c1"
BRANCH = "fix/preflight-timeout-confirmation"
WORKFLOW = Path(".github/workflows/one-shot-preflight-timeout-confirmation.yml")
SELF = Path("scripts/ci/one_shot_preflight_timeout_confirmation.py")
LAUNCHER = Path("scripts/ci/contextual_orchestrator_review_launcher.py")
TESTS = Path("tests/test_contextual_orchestrator_review_runtime_preflight.py")


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one repository command with visible output."""
    return subprocess.run(args, text=True, check=check)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact source fragment or fail closed on drift."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source match, found {count}")
    return text.replace(old, new, 1)


def append_regression_tests() -> None:
    """Append focused RED tests that reproduce timeout-only false rejection."""
    text = TESTS.read_text(encoding="utf-8")
    marker = "def test_preflight_timeout_confirmation_recovers_a_cold_route() -> None:"
    if marker in text:
        raise RuntimeError("timeout-confirmation regression tests already exist")
    appendix = r'''


def test_preflight_timeout_confirmation_recovers_a_cold_route() -> None:
    """One timeout is inconclusive; an identical confirmation may prove readiness."""
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]
    agent = SimpleNamespace(
        id="nvidia_cold_route",
        provider_name="nvidia_nim",
        model="provider/cold-route",
    )
    client = _SequencedClient(
        [TimeoutError("first response timed out"), _openai_text("OK")]
    )

    viable, report = preflight([agent], client=client)

    assert viable == [agent]
    assert len(client.calls) == 2
    assert [call[2]["max_tokens"] for call in client.calls] == [16, 16]
    assert report["ready_count"] == 1
    assert report["rejected_count"] == 0
    assert report["routes"] == [
        {
            "agent_id": "nvidia_cold_route",
            "provider": "nvidia_nim",
            "model": "provider/cold-route",
            "attempts": 2,
            "timeout_retries": 1,
            "status": "ready",
            "finish_reason": "unknown",
            "reasoning_without_content": False,
        }
    ]


def test_preflight_timeout_confirmation_is_bounded_after_two_timeouts() -> None:
    """Two timeouts fail closed without an unbounded per-route retry loop."""
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]
    preflight_error = namespace["ReviewPreflightError"]
    agent = SimpleNamespace(
        id="nvidia_still_timing_out",
        provider_name="nvidia_nim_sub",
        model="provider/still-timing-out",
    )
    client = _SequencedClient(
        [TimeoutError("first timeout"), TimeoutError("confirmation timeout")]
    )

    with pytest.raises(preflight_error) as caught:
        preflight([agent], client=client)

    assert len(client.calls) == 2
    row = caught.value.report["routes"][0]
    assert row["status"] == "rejected"
    assert row["error_type"] == "TimeoutError"
    assert row["attempts"] == 2
    assert row["timeout_retries"] == 1
    assert "first timeout" not in repr(caught.value.report)
    assert "confirmation timeout" not in repr(caught.value.report)


def test_preflight_timeout_confirmation_does_not_retry_http_rejection() -> None:
    """A concrete HTTP rejection remains terminal instead of consuming a retry."""
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]
    preflight_error = namespace["ReviewPreflightError"]

    class Http404Error(RuntimeError):
        """Synthetic provider rejection carrying only a bounded HTTP status."""

        code = 404

    agent = SimpleNamespace(
        id="nvidia_retired_model",
        provider_name="nvidia_nim",
        model="provider/retired-model",
    )
    client = _SequencedClient([Http404Error("do not persist this body")])

    with pytest.raises(preflight_error) as caught:
        preflight([agent], client=client)

    assert len(client.calls) == 1
    row = caught.value.report["routes"][0]
    assert row["status"] == "rejected"
    assert row["error_type"] == "Http404Error"
    assert row["http_status"] == 404
    assert row["attempts"] == 1
    assert "timeout_retries" not in row
    assert "do not persist this body" not in repr(caught.value.report)


def test_preflight_timeout_confirmation_preserves_budget_escalation_accounting() -> None:
    """A recovered base timeout and token escalation count every real request."""
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]
    agent = SimpleNamespace(
        id="nvidia_cold_reasoner",
        provider_name="nvidia_nim",
        model="provider/cold-reasoner",
    )
    client = _SequencedClient(
        [
            TimeoutError("cold start"),
            {"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
            _openai_text("OK"),
        ]
    )

    viable, report = preflight([agent], client=client)

    assert viable == [agent]
    assert [call[2]["max_tokens"] for call in client.calls] == [16, 16, 4096]
    row = report["routes"][0]
    assert row["status"] == "ready"
    assert row["attempts"] == 3
    assert row["timeout_retries"] == 1
    assert row["escalated"] is True
    assert report["escalations_used"] == 1


def test_preflight_timeout_confirmation_covers_the_escalated_stage() -> None:
    """The larger-budget probe receives the same one-time timeout confirmation."""
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]
    agent = SimpleNamespace(
        id="nvidia_slow_escalation",
        provider_name="nvidia_nim_sub",
        model="provider/slow-escalation",
    )
    client = _SequencedClient(
        [
            {"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
            TimeoutError("first escalated request timed out"),
            _openai_text("OK"),
        ]
    )

    viable, report = preflight([agent], client=client)

    assert viable == [agent]
    assert [call[2]["max_tokens"] for call in client.calls] == [16, 4096, 4096]
    row = report["routes"][0]
    assert row["status"] == "ready"
    assert row["attempts"] == 3
    assert row["timeout_retries"] == 1
    assert row["escalated"] is True
    assert report["escalations_used"] == 1
'''
    TESTS.write_text(text + appendix, encoding="utf-8")


def prove_red() -> None:
    """Require the new tests to fail against the unmodified implementation."""
    result = run(
        "python",
        "-m",
        "pytest",
        "-q",
        str(TESTS),
        "-k",
        "preflight_timeout_confirmation",
        check=False,
    )
    if result.returncode != 1:
        raise RuntimeError(
            f"RED gate expected pytest status 1, observed {result.returncode}"
        )


def patch_launcher() -> None:
    """Add one caller-owned timeout confirmation without retrying rejections."""
    launcher = LAUNCHER.read_text(encoding="utf-8")
    helper_anchor = '''    row.pop("finish_reason", None)\n    row.pop("reasoning_without_content", None)\n\n\ndef _response_has_reasoning_without_content(response: object) -> bool:\n'''
    helper_replacement = '''    row.pop("finish_reason", None)\n    row.pop("reasoning_without_content", None)\n\n\ndef _is_preflight_timeout(exc: Exception) -> bool:\n    """Return whether a provider exception is a direct or wrapped timeout."""\n    if isinstance(exc, TimeoutError):\n        return True\n    return isinstance(getattr(exc, "reason", None), TimeoutError)\n\n\ndef _send_preflight_probe(\n    agent: object,\n    *,\n    client: Any,\n    payload: dict[str, object],\n    row: dict[str, object],\n) -> object:\n    """Send one read-only probe and confirm a transport timeout exactly once.\n\n    ``ModelClient.proxy_send_once`` deliberately remains a one-shot transport.\n    This caller owns the only additional request because a timeout supplies no\n    provider response and therefore cannot, by itself, prove incompatibility.\n    Concrete HTTP rejections and every other exception remain single-attempt.\n    """\n    try:\n        return client.proxy_send_once(agent, "chat/completions", payload)\n    except Exception as exc:  # noqa: BLE001 - classify before the provider boundary\n        if not _is_preflight_timeout(exc):\n            raise\n        row["attempts"] = int(row.get("attempts", 0)) + 1\n        row["timeout_retries"] = int(row.get("timeout_retries", 0)) + 1\n        return client.proxy_send_once(agent, "chat/completions", payload)\n\n\ndef _response_has_reasoning_without_content(response: object) -> bool:\n'''
    launcher = replace_once(
        launcher, helper_anchor, helper_replacement, "timeout helper insertion"
    )
    launcher = replace_once(
        launcher,
        '''    enforce silently doubles. Every other failure class (transport exception,\n    non-2xx, or empty content matching neither signature) is not retried: a\n    genuinely-down candidate never reaches the escalation path, so it cannot\n    produce a false "healthy" read.\n''',
        '''    enforce silently doubles. A transport timeout supplies no provider response,\n    so the identical read-only request receives exactly one caller-owned\n    confirmation before the route is rejected for this startup. Concrete HTTP\n    rejections, other transport exceptions, and empty content matching neither\n    budget signature remain single-attempt.\n''',
        "preflight retry contract documentation",
    )
    launcher = replace_once(
        launcher,
        '''    The report deliberately records only stable route identity, a bounded\n    exception class name, an optional numeric HTTP status, attempt count, and\n    a bounded ``finish_reason``. Provider response bodies, exception\n''',
        '''    The report deliberately records only stable route identity, a bounded\n    exception class name, an optional numeric HTTP status, attempt count, the\n    optional number of timeout confirmations, and a bounded ``finish_reason``.\n    Provider response bodies, exception\n''',
        "preflight evidence documentation",
    )
    launcher = replace_once(
        launcher,
        '            response = client.proxy_send_once(agent, "chat/completions", base_payload)\n',
        '            response = _send_preflight_probe(\n                agent, client=client, payload=base_payload, row=row\n            )\n',
        "base preflight call",
    )
    launcher = replace_once(
        launcher,
        '        row["attempts"] = 2\n',
        '        row["attempts"] = int(row["attempts"]) + 1\n',
        "escalation attempt accounting",
    )
    launcher = replace_once(
        launcher,
        '''            escalated_response = client.proxy_send_once(\n                agent, "chat/completions", escalated_payload\n            )\n''',
        '''            escalated_response = _send_preflight_probe(\n                agent, client=client, payload=escalated_payload, row=row\n            )\n''',
        "escalated preflight call",
    )
    LAUNCHER.write_text(launcher, encoding="utf-8")


def update_documents() -> None:
    """Record the live incident, decision, and repaired contract."""
    changelog_path = Path("CHANGELOG.md")
    changelog = changelog_path.read_text(encoding="utf-8")
    changelog_marker = (
        "- **Confirm timeout-only review-route failures before rejecting the route.**"
    )
    if changelog_marker in changelog:
        raise RuntimeError("changelog entry already exists")
    changelog_entry = '''- **Confirm timeout-only review-route failures before rejecting the route.**\n  Live `seedream_evasepic` run `33480380500`, job `99768446738` rejected three\n  NVIDIA NIM routes after one `TimeoutError` each while four retired model paths\n  returned concrete HTTP 404 responses. The central sidecar now repeats only the\n  identical, read-only candidate probe once after a direct or wrapped timeout;\n  HTTP rejection, authentication, malformed-response, and other exception paths\n  remain single-attempt. Evidence records exact request count and\n  `timeout_retries`, including token-budget escalation stages.\n'''
    changelog = replace_once(
        changelog,
        "## [Unreleased]\n",
        "## [Unreleased]\n" + changelog_entry,
        "changelog insertion",
    )
    changelog_path.write_text(changelog, encoding="utf-8")

    adr_path = Path("docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md")
    adr = adr_path.read_text(encoding="utf-8")
    adr_marker = "## 2026-09-01 amendment: timeout is not rejection evidence"
    if adr_marker in adr:
        raise RuntimeError("ADR timeout amendment already exists")
    adr += '''\n\n## 2026-09-01 amendment: timeout is not rejection evidence\n\nRuntime evidence from `ContextualWisdomLab/seedream_evasepic` run\n`33480380500`, job `99768446738` showed a categorical mismatch: four routes\nreturned HTTP 404 and three different routes produced one `TimeoutError` each,\nyet all seven were recorded identically as rejected after one attempt. An HTTP\nresponse can prove a concrete provider/model rejection; a transport timeout has\nno response body or status and is therefore absence of evidence, not equivalent\nevidence.\n\nThe per-candidate preflight now confirms only a timeout once with the identical\nread-only payload and candidate. This does not change `ModelClient`'s one-shot\ntransport contract, restore a sidecar-wide deadline, retry HTTP/authentication or\nmalformed-response failures, or admit a route without usable text. A second\ntimeout still fails closed for that startup. The evidence row records total\n`attempts` and `timeout_retries`, so future reliability decisions use observed\nresults rather than treating one transport deadline as a permanent endpoint\ncapability verdict.\n'''
    adr_path.write_text(adr, encoding="utf-8")

    baseline_path = Path("docs/product-technical-gap-baseline.md")
    baseline = baseline_path.read_text(encoding="utf-8")
    baseline_marker = "## 2026-09-01 seedream_evasepic timeout-only route rejection"
    if baseline_marker in baseline:
        raise RuntimeError("gap-baseline incident entry already exists")
    baseline += '''\n\n## 2026-09-01 seedream_evasepic timeout-only route rejection\n\nFresh live-state inspection of run `33480380500`, job `99768446738` found 12\nprovider candidates: five ready, four rejected with HTTP 404, and three marked\nrejected after a single `TimeoutError`. The 404 rows are concrete stale\nprovider/model paths. The timeout rows did not contain an HTTP response and did\nnot establish endpoint incompatibility, but the launcher previously called\n`_record_provider_exception()` immediately after the first one-shot transport\nexception.\n\nThe repair adds one identical read-only confirmation only for direct or wrapped\ntimeouts, preserves single-attempt handling for every concrete HTTP and\nnon-timeout failure, counts all requests across base and token-escalated probes,\nand remains fail-closed if the confirmation also times out. This closes the\nclassification gap without changing the production serving timeout or reviving\nthe superseded sidecar-wide fixed-deadline design.\n'''
    baseline_path.write_text(baseline, encoding="utf-8")


def verify_green() -> None:
    """Run focused and surrounding exact-source verification."""
    run(
        "python",
        "-m",
        "pytest",
        "-q",
        str(TESTS),
        "-k",
        "preflight_timeout_confirmation",
    )
    run(
        "python",
        "-m",
        "pytest",
        "-q",
        str(TESTS),
        "tests/test_contextual_orchestrator_review_sidecar_contract.py",
        "tests/test_strix_contextual_orchestrator_contract.py",
    )
    run("python", "-m", "compileall", "-q", "scripts/ci")
    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    expected = {"_is_preflight_timeout", "_send_preflight_probe"}
    documented = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and ast.get_docstring(node)
    }
    missing = expected - documented
    if missing:
        raise RuntimeError(f"missing repair docstrings: {sorted(missing)}")
    run("git", "diff", "--check")


def publish() -> None:
    """Delete the self-modifying workflow and push one final reviewed commit."""
    WORKFLOW.unlink()
    SELF.unlink()
    run("git", "diff", "--check")
    run("git", "config", "user.name", "ContextualWisdomLab repair agent")
    run("git", "config", "user.email", "actions@users.noreply.github.com")
    run("git", "add", "-A")
    run("git", "commit", "-m", "fix(ci): confirm preflight timeouts before route rejection")
    run("git", "push", "origin", f"HEAD:{BRANCH}")


def main() -> None:
    """Execute the RED-to-GREEN timeout classification repair once."""
    run("git", "merge-base", "--is-ancestor", BASE_SHA, "HEAD")
    append_regression_tests()
    prove_red()
    patch_launcher()
    update_documents()
    verify_green()
    publish()


if __name__ == "__main__":
    main()
