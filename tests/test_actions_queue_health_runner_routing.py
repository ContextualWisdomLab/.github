"""Keep routing observations distinct from runner and isolation authority."""

import json

import pytest

from tests.test_actions_queue_health import NOW, queue_health, report_snapshot


def snapshot_with_routing(**routing):
    """Attach raw REST routing metadata to one current-head queued job."""
    snapshot = report_snapshot()
    snapshot['repositories'][0]['runs'][0]['jobs'][0].update(routing)
    return snapshot


def test_routing_survives_normalization_and_report_roundtrip():
    """Preserve labels and assigned group without inventing capacity or safety."""
    snapshot = snapshot_with_routing(labels=['self-hosted', 'Linux', 'cwlab-ci-isolated'],
                                    runner_group_id=13, runner_group_name='CWL CI isolated')
    repo = snapshot['repositories'][0]
    repo['runs'] = [queue_health._normalise_run(repo['full_name'], run, run['jobs'])
                    for run in repo['runs']]
    report = queue_health.build_report(json.loads(json.dumps(snapshot)), now=NOW)
    row = report['runs'][0]
    assert row['runner_labels'] == ['self-hosted', 'Linux', 'cwlab-ci-isolated']
    assert row['runner_group_id'] == 13
    assert row['runner_group_name'] == 'CWL CI isolated'
    assert row['runner_assigned'] is False
    assert row['execution_state'] == 'queued_unassigned'
    assert row['blocker'] == 'external_runner_assignment_or_capacity'
    assert 'GitHub-hosted runner assignment' not in ' '.join(report['summary']['external_actions'])


@pytest.mark.parametrize('routing', [{}, {'labels': None, 'runner_group_id': None, 'runner_group_name': None}])
def test_missing_routing_stays_unknown(routing):
    """Old snapshots and unavailable REST fields do not imply a missing group."""
    row = queue_health.build_report(snapshot_with_routing(**routing), now=NOW)['runs'][0]
    assert row['runner_labels'] is None
    assert row['runner_group_id'] is None
    assert row['runner_group_name'] is None


@pytest.mark.parametrize('routing', [
    {'labels': 'self-hosted'}, {'labels': [False]}, {'labels': ['']},
    {'runner_group_id': True}, {'runner_group_id': -1}, {'runner_group_id': '13'},
    {'runner_group_name': 13},
])
def test_malformed_routing_is_rejected(routing):
    """Reject ambiguous API fields instead of converting them to routing claims."""
    with pytest.raises(queue_health.QueueHealthError, match='runner'):
        queue_health.build_report(snapshot_with_routing(**routing), now=NOW)


def test_empty_routing_is_preserved_without_attestation():
    """Zero/unassigned group and empty labels are observations, never a pass."""
    row = queue_health.build_report(snapshot_with_routing(labels=[], runner_group_id=0,
                                    runner_group_name=''), now=NOW)['runs'][0]
    assert row['runner_labels'] == []
    assert row['runner_group_id'] == 0
    assert row['runner_group_name'] == ''
    assert not row['runner_assigned']


def test_collector_keeps_raw_rest_routing_through_json():
    """Exercise the public collector-to-report route with a fake read-only API."""
    from subprocess import CompletedProcess

    snapshot = snapshot_with_routing(labels=['self-hosted', 'linux'],
                                    runner_group_id=3, runner_group_name='control')
    repo = snapshot['repositories'][0]
    run = repo['runs'][0]
    jobs = run.pop('jobs')
    responses = {
        'repos/owner/repo': {'default_branch': 'main'},
        'repos/owner/repo/pulls?state=open&per_page=100': repo['pull_requests'],
        'repos/owner/repo/actions/runs?status=queued&per_page=50': [run],
        'repos/owner/repo/actions/runs?status=completed&head_sha=head&per_page=50': [],
        'repos/owner/repo/actions/runs?status=cancelled&event=pull_request_target&per_page=50': [],
        'repos/owner/repo/actions/runs/10/jobs?per_page=100': {'total_count': len(jobs), 'jobs': jobs},
    }
    for status in ('in_progress', 'pending', 'requested', 'waiting'):
        responses[f'repos/owner/repo/actions/runs?status={status}&per_page=50'] = []

    def runner(args, **kwargs):
        """Admit only the expected repository reads without network or mutation."""
        assert args[:2] == ['gh', 'api']
        return CompletedProcess(args, 0, json.dumps(responses[args[-1]]), '')

    collected = queue_health.collect_snapshot(['owner/repo'], runner=runner,
                                             generated_at='2026-08-19T12:00:00Z')
    assert not collected['collection_errors']
    row = queue_health.build_report(json.loads(json.dumps(collected)), now=NOW)['runs'][0]
    assert row['runner_labels'] == ['self-hosted', 'linux']
    assert row['runner_group_id'] == 3
    assert row['runner_group_name'] == 'control'
    assert not row['runner_assigned']
