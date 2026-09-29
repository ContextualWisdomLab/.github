"""Current-head suite bindings retain terminal proof without scanning old PRs."""

import json
from subprocess import CompletedProcess

import pytest

from tests.test_actions_queue_health_post_evidence_retry import queue_health

HEAD = 'a' * 40
ENDPOINT = 'repos/owner/repo/actions/runs?status=cancelled&event=pull_request_target&per_page=50'


@pytest.mark.parametrize('conclusion', ['cancelled', 'failure', 'startup_failure', 'success'])
def test_overflow_keeps_current_terminal_target_with_base_run_head(conclusion):
    """A canonical suite identifies the PR head without treating base SHA as it."""
    paths = []
    run = {'id': 11, 'check_suite_id': 7, 'event': 'pull_request_target',
           'head_sha': 'b' * 40, 'conclusion': conclusion}

    def runner(args, **kwargs):
        """Expose a huge history and three small immutable current-head suites."""
        path = args[-1]
        paths.append(path)
        if path == ENDPOINT:
            payload = {'total_count': 50000, 'workflow_runs': [{'id': 1}]}
        elif '/check-suites?' in path:
            payload = {'total_count': 3, 'check_suites': [
                {'id': 7, 'head_sha': HEAD,
                 'status': 'completed' if conclusion == 'startup_failure' else 'queued',
                 'conclusion': None if conclusion == 'startup_failure' else 'failure'},
                {'id': 8, 'head_sha': HEAD, 'status': 'completed', 'conclusion': 'success'},
                {'id': 9, 'head_sha': HEAD, 'conclusion': None},
            ]}
        elif 'check_suite_id=7&' in path:
            payload = {'total_count': 1, 'workflow_runs': [run]}
        else:
            raise AssertionError(path)
        return CompletedProcess(args, 0, json.dumps(payload), '')

    assert queue_health._read_target_terminal_runs(
        ENDPOINT, repository='owner/repo', heads=[HEAD], runner=runner,
    ) == ([] if conclusion == 'success' else [run])
    assert len(paths) == 3
    assert not any('page=2' in path or 'created=' in path for path in paths)


@pytest.mark.parametrize('malformed', ['read', 'suite_head', 'suite_id', 'suite_zero', 'run_suite', 'incomplete', 'run_incomplete', 'run_read'])
def test_suite_overflow_rejects_missing_or_misbound_evidence(malformed):
    """An API failure, incorrect immutable binding or partial list cannot pass."""
    def runner(args, **kwargs):
        """Serve one adversarial failure through the native pagination parser."""
        path = args[-1]
        if malformed == 'read' or (malformed == 'run_read' and 'check_suite_id=' in path):
            return CompletedProcess(args, 1, '', 'denied')
        if path == ENDPOINT:
            payload = {'total_count': 50000, 'workflow_runs': [{'id': 1}]}
        elif '/check-suites?' in path:
            payload = {'total_count': 2 if malformed == 'incomplete' else 1,
                       'check_suites': [{'id': True if malformed == 'suite_id' else 0 if malformed == 'suite_zero' else 7,
                                        'head_sha': 'wrong' if malformed == 'suite_head' else HEAD,
                                        'conclusion': 'cancelled'}]}
        else:
            payload = {'total_count': 2 if malformed == 'run_incomplete' else 1,
                       'workflow_runs': [{'id': 11, 'check_suite_id': 7 if malformed == 'run_incomplete' else 8}]}
        return CompletedProcess(args, 0, json.dumps(payload), '')

    with pytest.raises(queue_health.QueueHealthError) as error:
        queue_health._read_target_terminal_runs(
            ENDPOINT, repository='owner/repo', heads=[HEAD], runner=runner,
        )
    if malformed in {'run_incomplete', 'run_read'}:
        assert 'repos/owner/repo/actions/runs?check_suite_id=7&per_page=50' in str(error.value)


def test_overflow_with_no_open_heads_does_not_enumerate_closed_pr_history():
    """Closed-PR active work belongs to the active sweep, not terminal history."""
    paths = []

    def runner(args, **kwargs):
        """Declare an overflowing cancelled history on the first bounded page."""
        paths.append(args[-1])
        return CompletedProcess(args, 0, json.dumps({
            'total_count': 50000, 'workflow_runs': [{'id': 1}],
        }), '')

    assert queue_health._read_target_terminal_runs(
        ENDPOINT, repository='owner/repo', heads=[], runner=runner,
    ) == []
    assert paths == [ENDPOINT]


def test_overflow_reuses_already_collected_terminal_suite_run():
    """The complete native head query already owns this exact suite's run."""
    paths = []
    run = {'id': 11, 'check_suite_id': 7, 'head_sha': HEAD, 'conclusion': 'cancelled'}

    def runner(args, **kwargs):
        """Reject a redundant run read after serving the complete suite list."""
        path = args[-1]
        paths.append(path)
        if path == ENDPOINT:
            payload = {'total_count': 50000, 'workflow_runs': [{'id': 1}]}
        elif '/check-suites?' in path:
            payload = {'total_count': 1, 'check_suites': [
                {'id': 7, 'head_sha': HEAD, 'status': 'completed', 'conclusion': 'cancelled'},
            ]}
        else:
            raise AssertionError(path)
        return CompletedProcess(args, 0, json.dumps(payload), '')

    assert queue_health._read_target_terminal_runs(
        ENDPOINT, repository='owner/repo', heads=[HEAD], known_runs=[run, {"check_suite_id": None},
            {"check_suite_id": True}, {"check_suite_id": 0}], runner=runner,
    ) == [run]
    assert len(paths) == 2
