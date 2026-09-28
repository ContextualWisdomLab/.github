"""Exercise startup with a pending provider and shared probe budgets."""

import runpy
import threading
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest


LAUNCHER = Path(__file__).resolve().parents[1] / 'scripts/ci/contextual_orchestrator_review_launcher.py'


def agents(count):
    """Build distinct candidate routes without provider credentials."""
    return [SimpleNamespace(id=str(i), model=str(i), provider_name='nvidia_nim') for i in range(count)]


def text_response():
    """Return a minimal successful provider completion."""
    return {'choices': [{'message': {'content': 'OK'}}]}


def provider_http_error(status: int, body: str, released: list[int]) -> HTTPError:
    """Build a synthetic provider response the preflight must close itself."""

    class _TrackedHTTPError(HTTPError):
        """Count a close that happens after classification, not before raise."""

        def close(self) -> None:
            released.append(self.code)
            super().close()

    return _TrackedHTTPError('https://provider.invalid', status, body, {}, None)


@pytest.mark.parametrize("pending", [1, 8])
def test_pending_routes_do_not_block_eight_ready_routes(pending):
    """Retain pending inference while serving only completed, validated routes."""
    namespace = runpy.run_path(str(LAUNCHER))
    release = threading.Event()
    entered = threading.Event()
    finished = threading.Event()
    result = []

    class Client:
        """Keep the first route pending until the test explicitly releases it."""
        def proxy_send_once(self, agent, endpoint, payload):
            if int(agent.id) < pending:
                entered.set()
                release.wait()
            return text_response()

    def run():
        result.append(namespace['_preflight_review_agents_concurrently'](agents(pending + 8), client=Client()))
        finished.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        assert entered.wait(3), 'pending route was never invoked'
        assert finished.wait(3), 'pending inference blocked otherwise ready routes'
        viable, report = result[0]
        assert len(viable) == report['ready_count'] == 8
        assert [agent.id for agent in viable] == [str(i) for i in range(pending, pending + 8)]
        assert report['pending_count'] == pending
        assert next(row for row in report['routes'] if row['agent_id'] == '0')['status'] == 'pending'
        assert not release.is_set(), 'the scheduler must not cancel the pending provider'
    finally:
        release.set()
        thread.join(3)


def test_unavailable_pool_fails_closed_within_the_probe_budget():
    """Concurrent completion does not enlarge the committed probe budget."""
    namespace = runpy.run_path(str(LAUNCHER))
    calls = []
    released: list[int] = []

    class Client:
        """Return explicit provider rate-limit responses."""
        def proxy_send_once(self, agent, endpoint, payload):
            calls.append(agent.id)
            raise provider_http_error(429, 'private body', released)

    with pytest.raises(namespace['ReviewPreflightError']) as error:
        namespace['_preflight_review_agents_concurrently'](agents(24), client=Client())
    report = error.value.report
    assert released.count(429) == namespace['REVIEW_PREFLIGHT_MAX_PROBES']
    assert len(calls) == report['probed_count'] == namespace['REVIEW_PREFLIGHT_MAX_PROBES']
    assert report['ready_count'] == report['pending_count'] == 0
    assert all(row['status'] == 'rejected' and row['http_status'] == 429 for row in report['routes'])
    assert 'private body' not in str(report)


def test_parallel_escalations_share_one_budget():
    """Several simultaneous reasoning-only responses still spend at most four retries."""
    namespace = runpy.run_path(str(LAUNCHER))
    escalated = []

    class Client:
        """Require an escalated completion budget for every route."""
        def proxy_send_once(self, agent, endpoint, payload):
            if payload['max_tokens'] == namespace['REVIEW_PREFLIGHT_BASE_TOKENS']:
                return {'choices': [{'finish_reason': 'length', 'message': {'reasoning': 'pending'}}]}
            escalated.append(agent.id)
            return text_response()

    viable, report = namespace['_preflight_review_agents_concurrently'](agents(24), client=Client())
    assert len(escalated) == report['escalations_used'] == namespace['REVIEW_PREFLIGHT_MAX_ESCALATIONS']
    assert len(viable) == report['ready_count'] == len(escalated)
    assert report['probed_count'] == namespace['REVIEW_PREFLIGHT_MAX_PROBES']


def test_completed_transient_routes_are_deferred_only_with_a_ready_route():
    """Only explicit retryable responses are retained behind a proven route."""
    namespace = runpy.run_path(str(LAUNCHER))
    released: list[int] = []

    class Client:
        """Provide one ready route, a rate limit, and a permanent denial."""
        def proxy_send_once(self, agent, endpoint, payload):
            if agent.id != '2':
                status = 429 if agent.id == '0' else 401
                raise provider_http_error(status, 'private', released)
            return text_response()

    viable, report = namespace['_preflight_review_agents_concurrently'](agents(3), client=Client())
    assert sorted(released) == [401, 429]
    assert [agent.id for agent in viable] == ['2', '0']
    assert (report['ready_count'], report['deferred_count'], report['rejected_count']) == (1, 1, 1)
    assert report['pending_count'] == 0


def test_parallel_fallback_keeps_the_shared_escalation_budget():
    """Priced fallback starts only after primary rejection and spends the remainder."""
    namespace = runpy.run_path(str(LAUNCHER))
    primary = agents(2)
    fallback = agents(4)
    for agent in fallback:
        agent.id = 'fallback-' + agent.id
    calls = []
    released: list[int] = []

    class Client:
        """Primary escalation still rejects; fallback escalation can succeed."""
        def proxy_send_once(self, agent, endpoint, payload):
            calls.append(agent.id)
            if payload['max_tokens'] == namespace['REVIEW_PREFLIGHT_BASE_TOKENS']:
                return {'choices': [{'finish_reason': 'length', 'message': {'reasoning': 'pending'}}]}
            if agent.id.startswith('fallback-'):
                return text_response()
            raise provider_http_error(400, 'rejected', released)

    viable, report, used = namespace['_preflight_with_fallback'](
        primary, fallback, client=Client(), preflight=namespace['_preflight_review_agents_concurrently'],
    )
    assert used and len(viable) == 2
    assert released.count(400) == 2
    assert report['primary_attempt']['escalations_used'] == 2
    assert report['escalations_used'] == namespace['REVIEW_PREFLIGHT_MAX_ESCALATIONS']
    assert calls[:4].count('0') == calls[:4].count('1') == 2


def test_unexpected_worker_fault_reaches_the_launcher():
    """Do not turn a worker programming fault into a rejected provider route."""
    namespace = runpy.run_path(str(LAUNCHER))

    class Fatal(BaseException):
        """Represent an exception outside the provider's ordinary failure boundary."""

    class Client:
        """Raise the test's explicit lifecycle fault."""
        def proxy_send_once(self, agent, endpoint, payload):
            raise Fatal()

    with pytest.raises(Fatal):
        namespace['_preflight_review_agents_concurrently'](agents(1), client=Client())


def test_production_startup_uses_the_concurrent_scheduler():
    """The launcher must wire the repair into the shared serving entry point."""
    source = LAUNCHER.read_text(encoding='utf-8').split('def main(', 1)[1]
    assert 'preflight=_preflight_review_agents_concurrently,' in source
