"""PolicyWeave supplier parity against the deployed consumer contract."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/policyweave-quality.yml'


def test_supplier_preserves_verification_and_isolation():
    """Require a fixed reusable supplier with all product gates retained."""
    assert WORKFLOW.is_file(), 'PolicyWeave reusable supplier is missing'
    data = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    assert data['on'] == {'workflow_call': ''}
    assert data['permissions'] == {'contents': 'read'}
    assert 'concurrency' not in data
    assert set(data['jobs']) == {'verify'}
    job = data['jobs']['verify']
    assert 'if' not in job
    assert job['runs-on'] == {'group': 'CWL CI isolated', 'labels': ['self-hosted', 'linux', 'x64', 'cwlab-ci-isolated']}
    pg = job['services']['postgres']
    assert pg['image'] == 'postgres@sha256:d3e1620b530c944afa6e887d22eb899824da68e19c52024bf98f5220c88a65b2'
    assert pg['ports'] == ['5432']
    steps = job['steps']
    checkout = next(s for s in steps if s.get('uses', '').startswith('actions/checkout@'))
    assert checkout['with'] == {'persist-credentials': 'false', 'ref': '${{ github.sha }}'}
    identity = next(s for s in steps if s.get('run') == 'test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD_SHA"')
    assert identity['env'] == {'EXPECTED_HEAD_SHA': '${{ github.sha }}'}
    commands = [s['run'] for s in steps if 'run' in s]
    for command in ['npm ci --include=dev', 'npm run lint', 'npm test', 'npm run build', 'sh db/tests/policy_revision_runtime.sh', 'sh db/tests/policy_revision_concurrency.sh', 'sh db/tests/policy_revision_restore.sh', 'npm run test:e2e']:
        assert command in commands
    assert any('npm sbom --sbom-format cyclonedx' in c for c in commands)
    for step in steps:
        assert not step.get('continue-on-error')
        if 'uses' in step:
            assert re.search(r'@[0-9a-f]{40}$', step['uses'])
        if step.get('run', '').startswith('sh db/tests/'):
            assert step['env']['PGPORT'] == "${{ job.services.postgres.ports['5432'] }}"
    assert job['env']['NODE_ENV'] == 'test'
    assert next(s for s in steps if s.get('run') == 'npm run build')['env']['NODE_ENV'] == 'production'
    uploads = [s for s in steps if s.get('uses', '').startswith('actions/upload-artifact@')]
    assert len(uploads) == 2
    assert uploads[1]['with']['if-no-files-found'] == 'error'


def test_actual_event_head_guard_rejects_forks_and_stale_refs():
    """Execute the supplier's first shell step, not a textual approximation."""
    import subprocess

    data = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    step = data['jobs']['verify']['steps'][0]
    script = step['run']
    base = {
        'PATH': '/usr/bin:/bin',
        'TARGET_REPOSITORY': 'ContextualWisdomLab/PolicyWeave',
        'EVENT_NAME': 'pull_request',
        'CALLER_REF': 'refs/pull/42/merge',
        'CALLER_SHA': 'a' * 40,
        'PR_NUMBER': '42',
        'PR_STATE': 'open',
        'PR_DRAFT': 'false',
        'PR_HEAD_REPOSITORY': 'ContextualWisdomLab/PolicyWeave',
        'PR_BASE_REPOSITORY': 'ContextualWisdomLab/PolicyWeave',
        'PR_BASE_REF': 'main',
        'PR_HEAD_SHA': 'b' * 40,
    }

    def run(env):
        return subprocess.run(
            ['/bin/bash', '--noprofile', '--norc', '-e', '-o', 'pipefail', '-c', script],
            env=env, capture_output=True, text=True, timeout=5,
        )

    for base_ref in ('main', 'develop', 'agent'):
        for draft in ('false', 'true'):
            accepted = run({**base, 'PR_BASE_REF': base_ref, 'PR_DRAFT': draft})
            assert accepted.returncode == 0, accepted.stderr

    for ref in ('refs/heads/main', 'refs/heads/develop'):
        accepted = run({**base, 'EVENT_NAME': 'push', 'CALLER_REF': ref})
        assert accepted.returncode == 0, accepted.stderr

    for mutation in [
        {'TARGET_REPOSITORY': 'attacker/PolicyWeave'},
        {'PR_HEAD_REPOSITORY': 'attacker/PolicyWeave'},
        {'PR_BASE_REPOSITORY': 'attacker/PolicyWeave'},
        {'EVENT_NAME': 'workflow_dispatch'},
        {'CALLER_REF': 'refs/pull/42/head'},
        {'PR_NUMBER': 'not-a-number'},
        {'PR_HEAD_SHA': 'not-a-sha'},
        {'CALLER_SHA': 'not-a-sha'},
        {'EVENT_NAME': 'push', 'CALLER_REF': 'refs/heads/feature'},
        {'EVENT_NAME': 'push', 'CALLER_REF': 'refs/heads/main', 'CALLER_SHA': 'not-a-sha'},
    ]:
        result = run({**base, **mutation})
        assert result.returncode != 0
        assert 'attacker' not in result.stdout + result.stderr
