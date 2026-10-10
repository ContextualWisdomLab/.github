"""Keep PR merge-tree execution off privileged OpenCode/control runners."""

from copy import deepcopy
from pathlib import Path
import re

import pytest
import yaml


WORKFLOW = Path('.github/workflows/opencode-review-dispatch.yml')
ISOLATED = {
    'group': 'CWL CI isolated',
    'labels': ['self-hosted', 'linux', 'x64', 'cwlab-ci-isolated'],
}


def assert_pr_workload_isolated(jobs: dict) -> None:
    """Require every identified PR coverage executor to use the isolated route."""
    observed = 0
    for job_id, job in jobs.items():
        runs = '\n'.join(str(step.get('run', '')) for step in job.get('steps', []))
        executes_tests = re.search(r'\b(pytest|coverage run|npm (?:run |)test|pnpm (?:run |)test)\b', runs)
        if job_id == 'coverage-evidence' or ('COVERAGE_SOURCE_WORKDIR' in runs and executes_tests):
            observed += 1
            assert job.get('runs-on') == ISOLATED, (
                f'{job_id}: PR merge-tree execution requires the exact isolated runner mapping; '
                f'got {job.get("runs-on")!r}'
            )
    assert observed, 'No PR merge-tree workload was checked'


def test_actual_pr_merge_tree_execution_requires_isolated_runner() -> None:
    """Reject the actual workflow's privileged-pool PR test execution."""
    assert_pr_workload_isolated(yaml.safe_load(WORKFLOW.read_text())['jobs'])


@pytest.mark.parametrize('runner', [
    {'group': 'CWL central OpenCode', 'labels': ['self-hosted', 'linux', 'x64']},
    {'group': 5, 'labels': ['self-hosted', 'linux', 'x64']},
    {'group': 'CWL central control', 'labels': ['self-hosted', 'linux', 'x64']},
    {'group': 'CWL CI isolated', 'labels': ['self-hosted', 'linux', 'x64']},
    '${{ fromJSON(inputs.runner) }}',
])
def test_equivalent_renamed_pr_workload_rejects_nonisolated_mapping(runner) -> None:
    """A renamed executor cannot evade group or required-label admission."""
    job = {
        'runs-on': deepcopy(ISOLATED),
        'steps': [{'run': 'cd "$COVERAGE_SOURCE_WORKDIR" && python3 -m pytest tests'}],
    }
    assert_pr_workload_isolated({'renamed-pr-tests': job})
    job['runs-on'] = runner
    with pytest.raises(AssertionError, match='requires the exact isolated runner mapping'):
        assert_pr_workload_isolated({'renamed-pr-tests': job})


def test_metadata_and_publisher_keep_privileged_permissions_separate() -> None:
    """Preserve trusted token jobs and the PR executor's read-only artifact access."""
    jobs = yaml.safe_load(WORKFLOW.read_text())['jobs']
    for job_id in ('validate-pr-metadata', 'opencode-review-target'):
        assert jobs[job_id]['runs-on'] == {
            'group': 'CWL central OpenCode', 'labels': ['self-hosted', 'linux', 'x64'],
        }
    assert jobs['validate-pr-metadata']['permissions'] == {
        'contents': 'read', 'pull-requests': 'read', 'id-token': 'write',
    }
    coverage = jobs['coverage-evidence']
    assert coverage['permissions'] == {'actions': 'read'}
    assert coverage['needs'] == ['validate-pr-metadata']
    assert coverage['timeout-minutes'] == 300
    assert coverage['outputs'] == {
        'coverage_summary': '${{ steps.measure.outputs.coverage_summary }}',
    }
    assert jobs['opencode-review-target']['needs'] == ['validate-pr-metadata', 'coverage-evidence']
    assert jobs['opencode-review-target']['permissions']['pull-requests'] == 'write'
    assert jobs['opencode-review-target']['permissions']['id-token'] == 'write'
