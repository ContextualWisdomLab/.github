"""Executable admission and lane contracts for the fixed pg-erd consumer."""

import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / '.github/workflows/pg-erd-cloud-quality.yml'


def workflow():
    """Load with BaseLoader so GitHub's on key is not parsed as YAML 1.1 bool."""
    return yaml.load(PATH.read_text(), Loader=yaml.BaseLoader)


def test_fixed_reusable_scope():
    """No arbitrary executable inputs, secrets, or cancellation of its caller."""
    data = workflow()
    assert data['on'] == {'workflow_call': ''}
    assert data['permissions'] == {'contents': 'read'}
    assert 'concurrency' not in data
    assert set(data['jobs']) == {'backend', 'frontend'}
    for job in data['jobs'].values():
        assert job['runs-on'] == {'group': 'CWL CI isolated', 'labels': ['self-hosted', 'linux', 'x64', 'cwlab-ci-isolated']}
        assert job['timeout-minutes'] == '30'
        assert 'if' not in job
        assert job['steps'][0]['name'] == 'Admit fixed caller before checkout'
        assert 'uses' not in job['steps'][0]
        assert job['steps'][1]['uses'].startswith('step-security/harden-runner@')
        checkout = job['steps'][2]
        assert checkout['with']['persist-credentials'] == 'false'
        assert checkout['with']['ref'] == '${{ github.event.pull_request.head.sha || github.sha }}'
        for step in job['steps']:
            assert not step.get('continue-on-error')
            if 'uses' in step:
                assert re.search(r'@[0-9a-f]{40}$', step['uses'])


@pytest.mark.parametrize('job_name', ['backend', 'frontend'])
@pytest.mark.parametrize('event,repository,head,base,ref,expected', [
    ('pull_request', 'ContextualWisdomLab/pg-erd-cloud', 'ContextualWisdomLab/pg-erd-cloud', 'ContextualWisdomLab/pg-erd-cloud', 'refs/pull/1/merge', 0),
    ('pull_request', 'ContextualWisdomLab/pg-erd-cloud', 'attacker/fork', 'ContextualWisdomLab/pg-erd-cloud', 'refs/pull/1/merge', 1),
    ('push', 'ContextualWisdomLab/pg-erd-cloud', '', '', 'refs/heads/main', 0),
    ('push', 'ContextualWisdomLab/pg-erd-cloud', '', '', 'refs/heads/feature', 1),
    ('workflow_dispatch', 'ContextualWisdomLab/pg-erd-cloud', '', '', 'refs/heads/main', 0),
    ('workflow_dispatch', 'ContextualWisdomLab/pg-erd-cloud', '', '', 'refs/heads/feature', 1),
    ('pull_request_target', 'ContextualWisdomLab/pg-erd-cloud', 'ContextualWisdomLab/pg-erd-cloud', 'ContextualWisdomLab/pg-erd-cloud', 'refs/heads/main', 1),
    ('push', 'ContextualWisdomLab/.github', '', '', 'refs/heads/main', 1),
    ('pull_request', 'ContextualWisdomLab/pg-erd-cloud', 'ContextualWisdomLab/pg-erd-cloud', 'attacker/base', 'refs/pull/1/merge', 1),
])
def test_actual_admission_shell(job_name, event, repository, head, base, ref, expected):
    """Run the actual first step with allowed and rejected caller tuples."""
    step = workflow()['jobs'][job_name]['steps'][0]
    assert step['env'] == {
        'CALLER_REPOSITORY': '${{ github.repository }}', 'CALLER_EVENT': '${{ github.event_name }}',
        'PR_HEAD_REPOSITORY': '${{ github.event.pull_request.head.repo.full_name }}',
        'PR_BASE_REPOSITORY': '${{ github.event.pull_request.base.repo.full_name }}',
        'CALLER_REF': '${{ github.ref }}',
    }
    env = {'PATH': '/usr/bin:/bin', 'CALLER_REPOSITORY': repository, 'CALLER_EVENT': event,
           'PR_HEAD_REPOSITORY': head, 'PR_BASE_REPOSITORY': base, 'CALLER_REF': ref}
    result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-e', '-o', 'pipefail', '-c', step['run']], env=env, capture_output=True, text=True, timeout=5)
    assert result.returncode == expected
    assert 'attacker' not in result.stdout + result.stderr


def test_backend_environment_is_job_private():
    """Candidate dependencies cannot be installed into a shared runner Python."""
    steps = workflow()['jobs']['backend']['steps']
    install = next(s for s in steps if 'pip install' in s.get('run', ''))
    script = install['run']
    assert 'mktemp -d' in script
    assert 'python -m venv' in script
    assert 'trap ' in script and ' EXIT' in script
    assert 'PIP_NO_CACHE_DIR' in script
    assert install['shell'] == 'bash --noprofile --norc -e -o pipefail {0}'


@pytest.mark.parametrize('failed_tool, expected', [('', 0), ('mypy', 17), ('pytest', 17)])
def test_backend_shell_cleanup_and_failure_propagation(tmp_path, failed_tool, expected):
    """Execute the actual lane with synthetic tools; never install dependencies."""
    checkout = tmp_path / 'checkout'; checkout.mkdir()
    (checkout / 'backend').mkdir()
    runner_temp = tmp_path / 'runner-temp'; runner_temp.mkdir()
    sentinel = runner_temp / 'unrelated'; sentinel.write_text('keep')
    tools = tmp_path / 'tools'; tools.mkdir()
    trace = tmp_path / 'trace'
    python_stub = tools / 'python'
    python_stub.write_text('''#!/bin/bash
set -eu
printf 'python %s\\n' "$*" >> "$TRACE"
if [ "${1-}" = '-m' ] && [ "${2-}" = 'venv' ]; then
  mkdir -p "$3/bin"
  ln -s "$STUB_PYTHON" "$3/bin/python"
fi
''')
    python_stub.chmod(0o755)
    for tool in ['actionlint', 'shellcheck', 'mypy', 'pytest']:
        path = tools / tool
        path.write_text(f'''#!/bin/bash
printf '{tool}\\n' >> "$TRACE"
if [ "$FAILED_TOOL" = '{tool}' ]; then exit 17; fi
''')
        path.chmod(0o755)
    step = next(s for s in workflow()['jobs']['backend']['steps'] if 'pip install' in s.get('run', ''))
    env = {'PATH': f'{tools}:/usr/bin:/bin', 'RUNNER_TEMP': str(runner_temp),
           'TRACE': str(trace), 'STUB_PYTHON': str(python_stub), 'FAILED_TOOL': failed_tool}
    result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-e', '-o', 'pipefail', '-c', step['run']], cwd=checkout, env=env, capture_output=True, text=True, timeout=5)
    assert result.returncode == expected, result.stderr
    assert sorted(p.name for p in runner_temp.iterdir()) == ['unrelated']
    assert sentinel.read_text() == 'keep'
    lines = trace.read_text().splitlines()
    assert sum('pip install --require-hashes' in line for line in lines) == 2
    assert 'python -m unittest discover -s .github/tests -v' in lines
    if failed_tool == 'mypy':
        assert 'pytest' not in lines
    else:
        assert 'pytest' in lines


def test_preserved_product_commands():
    """Centralization keeps every existing backend/frontend validation command."""
    data = workflow()
    backend = data['jobs']['backend']; frontend = data['jobs']['frontend']
    commands = '\n'.join(s.get('run', '') for s in backend['steps'])
    for command in ['python -m pip install --require-hashes -r requirements-dev.lock',
                    'python -m pip install --require-hashes -r ../.github/requirements.lock',
                    'python -m unittest discover -s .github/tests -v',
                    'python .github/scripts/validate_codeql_backfill.py',
                    'actionlint .github/workflows/*.yml', 'shellcheck .github/scripts/*.sh',
                    'mypy app', 'pytest -q']:
        assert command in commands
    frontend_commands = '\n'.join(s.get('run', '') for s in frontend['steps'])
    for command in ['npm ci --include=dev', 'npm run typecheck', 'npm run test', 'npm run build']:
        assert command in frontend_commands
    assert frontend['env']['NODE_ENV'] == 'test'
    assert next(s for s in frontend['steps'] if s['name'] == 'Build')['env']['NODE_ENV'] == 'production'
    assert all('runner.' not in str(v) for j in data['jobs'].values() for v in j.get('env', {}).values())
