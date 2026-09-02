from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

BOOTSTRAP = Path("scripts/ci/one_shot_preflight_timeout_confirmation.py")
SELF = Path("scripts/ci/run_one_shot_preflight_timeout_confirmation.py")


def load_bootstrap() -> ModuleType:
    """Load the reviewed one-shot module without invoking its entry point."""
    spec = importlib.util.spec_from_file_location("timeout_confirmation_bootstrap", BOOTSTRAP)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {BOOTSTRAP}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_stable_source_patch(module: ModuleType) -> None:
    """Replace the bootstrap's overly specific helper insertion anchor."""

    def patch_launcher() -> None:
        """Add one caller-owned timeout confirmation without retrying rejections."""
        launcher = module.LAUNCHER.read_text(encoding="utf-8")
        function_marker = (
            "\ndef _response_has_reasoning_without_content(response: object) -> bool:\n"
        )
        helper = '''
def _is_preflight_timeout(exc: Exception) -> bool:
    """Return whether a provider exception is a direct or wrapped timeout."""
    if isinstance(exc, TimeoutError):
        return True
    return isinstance(getattr(exc, "reason", None), TimeoutError)


def _send_preflight_probe(
    agent: object,
    *,
    client: Any,
    payload: dict[str, object],
    row: dict[str, object],
) -> object:
    """Send one read-only probe and confirm a transport timeout exactly once.

    ``ModelClient.proxy_send_once`` deliberately remains a one-shot transport.
    This caller owns the only additional request because a timeout supplies no
    provider response and therefore cannot, by itself, prove incompatibility.
    Concrete HTTP rejections and every other exception remain single-attempt.
    """
    try:
        return client.proxy_send_once(agent, "chat/completions", payload)
    except Exception as exc:  # noqa: BLE001 - classify before the provider boundary
        if not _is_preflight_timeout(exc):
            raise
        row["attempts"] = int(row.get("attempts", 0)) + 1
        row["timeout_retries"] = int(row.get("timeout_retries", 0)) + 1
        return client.proxy_send_once(agent, "chat/completions", payload)

'''
        launcher = module.replace_once(
            launcher,
            function_marker,
            "\n" + helper + function_marker.lstrip("\n"),
            "timeout helper insertion",
        )
        launcher = module.replace_once(
            launcher,
            '''    enforce silently doubles. Every other failure class (transport exception,
    non-2xx, or empty content matching neither signature) is not retried: a
    genuinely-down candidate never reaches the escalation path, so it cannot
    produce a false "healthy" read.
''',
            '''    enforce silently doubles. A transport timeout supplies no provider response,
    so the identical read-only request receives exactly one caller-owned
    confirmation before the route is rejected for this startup. Concrete HTTP
    rejections, other transport exceptions, and empty content matching neither
    budget signature remain single-attempt.
''',
            "preflight retry contract documentation",
        )
        launcher = module.replace_once(
            launcher,
            '''    The report deliberately records only stable route identity, a bounded
    exception class name, an optional numeric HTTP status, attempt count, and
    a bounded ``finish_reason``. Provider response bodies, exception
''',
            '''    The report deliberately records only stable route identity, a bounded
    exception class name, an optional numeric HTTP status, attempt count, the
    optional number of timeout confirmations, and a bounded ``finish_reason``.
    Provider response bodies, exception
''',
            "preflight evidence documentation",
        )
        launcher = module.replace_once(
            launcher,
            '            response = client.proxy_send_once(agent, "chat/completions", base_payload)\n',
            '            response = _send_preflight_probe(\n'
            '                agent, client=client, payload=base_payload, row=row\n'
            '            )\n',
            "base preflight call",
        )
        launcher = module.replace_once(
            launcher,
            '        row["attempts"] = 2\n',
            '        row["attempts"] = int(row["attempts"]) + 1\n',
            "escalation attempt accounting",
        )
        launcher = module.replace_once(
            launcher,
            '''            escalated_response = client.proxy_send_once(
                agent, "chat/completions", escalated_payload
            )
''',
            '''            escalated_response = _send_preflight_probe(
                agent, client=client, payload=escalated_payload, row=row
            )
''',
            "escalated preflight call",
        )
        module.LAUNCHER.write_text(launcher, encoding="utf-8")
        patch_stale_preexisting_timeout_tests(module)

    module.patch_launcher = patch_launcher


def patch_stale_preexisting_timeout_tests(module: ModuleType) -> None:
    """Bring three pre-existing tests in line with the new confirmation retry.

    ``patch_launcher`` above makes every escalated-probe transport timeout
    receive one caller-owned confirmation attempt before the route is
    rejected (and ``_preflight_with_fallback`` shares that same behavior for
    its primary-stage timeouts). Three tests already in
    ``tests/test_contextual_orchestrator_review_runtime_preflight.py``
    predate that change and assert the OLD single-attempt call counts; left
    unpatched they fail non-deterministically-looking but actually
    deterministic ways (``StopIteration`` instead of ``TimeoutError`` when a
    ``_SequencedClient`` fixture runs out of queued outcomes one call early,
    or a stale expected attempt/call count) on every platform, not just
    Windows. Bring their fixtures and expectations in line with the
    documented new contract instead of leaving them broken.
    """
    tests = module.TESTS.read_text(encoding="utf-8")
    tests = module.replace_once(
        tests,
        '''def test_escalated_probe_transport_failure_is_not_mislabeled_as_a_rejection() -> None:
    """A transport failure (no HTTP status at all) on the escalated attempt
    gets the same sanitized exception-type recording the base probe uses --
    no HTTP status means even less basis for any budget-specific label.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]

    flaky = SimpleNamespace(
        id="openrouter_flaky", provider_name="openrouter", model="flaky/free"
    )
    client = _SequencedClient(
        [
            {"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
            TimeoutError("connection timed out with zero bytes received"),
        ]
    )

    with pytest.raises(namespace["ReviewPreflightError"]) as failure:
        preflight([flaky], client=client)

    row = failure.value.report["routes"][0]
    assert row["error_type"] == "TimeoutError"
    assert "http_status" not in row
    assert row["attempts"] == 2
''',
        '''def test_escalated_probe_transport_failure_is_not_mislabeled_as_a_rejection() -> None:
    """A transport failure (no HTTP status at all) on the escalated attempt
    gets the same sanitized exception-type recording the base probe uses --
    no HTTP status means even less basis for any budget-specific label. The
    escalated attempt's one caller-owned timeout confirmation also times out
    here, so the route still fails closed after both attempts.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]

    flaky = SimpleNamespace(
        id="openrouter_flaky", provider_name="openrouter", model="flaky/free"
    )
    client = _SequencedClient(
        [
            {"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
            TimeoutError("connection timed out with zero bytes received"),
            TimeoutError("confirmation also timed out"),
        ]
    )

    with pytest.raises(namespace["ReviewPreflightError"]) as failure:
        preflight([flaky], client=client)

    row = failure.value.report["routes"][0]
    assert row["error_type"] == "TimeoutError"
    assert "http_status" not in row
    assert row["attempts"] == 3
''',
        "stale escalated-transport-failure fixture",
    )
    tests = module.replace_once(
        tests,
        '''def test_escalated_probe_transport_exception_clears_stale_base_attempt_diagnostics() -> None:
    """Regression for Devin Review's escalation-failures-retain-stale-
    diagnostics finding: when the escalated attempt raises an exception (no
    response object at all for that attempt), ``finish_reason`` and
    ``reasoning_without_content`` must not silently keep the BASE attempt's
    values -- the same mixed-attempt-telemetry bug class already fixed for
    the escalated-empty and escalated-success outcomes, here closed for the
    escalated-exception outcome too. This variant is a bare transport
    failure (no HTTP status at all).
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]

    flaky = SimpleNamespace(
        id="nvidia_nim_flaky_transport", provider_name="nvidia_nim", model="flaky/free"
    )
    client = _SequencedClient(
        [
            {"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
            TimeoutError("connection timed out with zero bytes received"),
        ]
    )

    with pytest.raises(namespace["ReviewPreflightError"]) as failure:
        preflight([flaky], client=client)

    row = failure.value.report["routes"][0]
    assert row["attempts"] == 2
    assert row["error_type"] == "TimeoutError"
    assert "http_status" not in row
    # The base attempt's finish_reason=="length"/reasoning_without_content
    # must not linger: there is no response for THIS (escalated) attempt to
    # describe, so both fields are simply absent.
    assert "finish_reason" not in row
    assert "reasoning_without_content" not in row
''',
        '''def test_escalated_probe_transport_exception_clears_stale_base_attempt_diagnostics() -> None:
    """Regression for Devin Review's escalation-failures-retain-stale-
    diagnostics finding: when the escalated attempt raises an exception (no
    response object at all for that attempt), ``finish_reason`` and
    ``reasoning_without_content`` must not silently keep the BASE attempt's
    values -- the same mixed-attempt-telemetry bug class already fixed for
    the escalated-empty and escalated-success outcomes, here closed for the
    escalated-exception outcome too. This variant is a bare transport
    failure (no HTTP status at all), confirmed once (per the new
    timeout-confirmation contract) before it is recorded as rejected.
    """
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]

    flaky = SimpleNamespace(
        id="nvidia_nim_flaky_transport", provider_name="nvidia_nim", model="flaky/free"
    )
    client = _SequencedClient(
        [
            {"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
            TimeoutError("connection timed out with zero bytes received"),
            TimeoutError("confirmation also timed out"),
        ]
    )

    with pytest.raises(namespace["ReviewPreflightError"]) as failure:
        preflight([flaky], client=client)

    row = failure.value.report["routes"][0]
    assert row["attempts"] == 3
    assert row["error_type"] == "TimeoutError"
    assert "http_status" not in row
    # The base attempt's finish_reason=="length"/reasoning_without_content
    # must not linger: there is no response for THIS (escalated) attempt to
    # describe, so both fields are simply absent.
    assert "finish_reason" not in row
    assert "reasoning_without_content" not in row
''',
        "stale escalated-transport-exception-clears-diagnostics fixture",
    )
    tests = module.replace_once(
        tests,
        'assert [call[0] for call in client.calls] == [primary, fallback]\n',
        'assert [call[0] for call in client.calls] == [primary, primary, fallback]\n',
        "stale primary-timeout-confirmed-before-fallback call count",
    )
    module.TESTS.write_text(tests, encoding="utf-8")


def install_cleanup(module: ModuleType) -> None:
    """Ensure both temporary Python drivers and the workflow self-delete."""

    def publish() -> None:
        """Delete bootstrap assets and push one final reviewed product commit."""
        module.WORKFLOW.unlink()
        module.SELF.unlink()
        SELF.unlink()
        module.run("git", "diff", "--check")
        module.run("git", "config", "user.name", "ContextualWisdomLab repair agent")
        module.run("git", "config", "user.email", "actions@users.noreply.github.com")
        module.run("git", "add", "-A")
        module.run(
            "git",
            "commit",
            "-m",
            "fix(ci): confirm preflight timeouts before route rejection",
        )
        module.run("git", "push", "origin", f"HEAD:{module.BRANCH}")

    module.publish = publish


def main() -> None:
    """Run the corrected one-shot RED-to-GREEN workflow."""
    module = load_bootstrap()
    install_stable_source_patch(module)
    install_cleanup(module)
    module.main()


if __name__ == "__main__":
    main()
